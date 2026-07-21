"""
ESM-2 masked-marginal scorer. This is the ONLY module in the whole system
that imports torch/transformers directly and runs a model forward pass.

Method: for each position i, mask it, run a forward pass, take log_softmax
over the model's amino-acid logits, and gather into AA_ORDER column order.
Positions are batched for throughput.
"""

import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoModelForMaskedLM, AutoTokenizer

from domain.scoring import AA_ORDER, validate_sequence

DEFAULT_REVISION = "08e4846e537177426273712802403f7ba8261b6c"  # pin for reproducibility
DEFAULT_CHECKPOINT = "facebook/esm2_t33_650M_UR50D"


def pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class ESM2Scorer:
    model_id = "esm2_t33_650M_UR50D"

    def __init__(
        self,
        checkpoint: str = DEFAULT_CHECKPOINT,
        revision: str = DEFAULT_REVISION,
        device: str | None = None,
        batch_size: int = 8,
    ) -> None:
        self.device = device or pick_device()
        self.batch_size = batch_size
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint, revision=revision)
        self.model = AutoModelForMaskedLM.from_pretrained(checkpoint, revision=revision)
        self.model.to(self.device)
        self.model.eval()

        # Map AA_ORDER -> this tokenizer's vocab ids, once, at load time.
        self._aa_token_ids = [self.tokenizer.convert_tokens_to_ids(aa) for aa in AA_ORDER]
        if any(i is None or i == self.tokenizer.unk_token_id for i in self._aa_token_ids):
            raise RuntimeError(
                "Tokenizer failed to map one or more AA_ORDER residues to known tokens"
            )

    @torch.no_grad()
    def per_position_log_probs(self, sequence: str) -> np.ndarray:
        validate_sequence(sequence)
        L = len(sequence)

        base_ids = self.tokenizer(sequence, return_tensors="pt")["input_ids"][0]
        mask_id = self.tokenizer.mask_token_id
        # position i in `sequence` is base_ids[i + 1] (index 0 is <cls>)

        M = np.zeros((L, len(AA_ORDER)), dtype=np.float32)

        for batch_start in range(0, L, self.batch_size):
            batch_positions = list(range(batch_start, min(batch_start + self.batch_size, L)))
            batch_input_ids = base_ids.unsqueeze(0).repeat(len(batch_positions), 1).clone()
            for row, pos in enumerate(batch_positions):
                batch_input_ids[row, pos + 1] = mask_id  # +1 skips <cls>

            batch_input_ids = batch_input_ids.to(self.device)
            attention_mask = torch.ones_like(batch_input_ids)
            logits = self.model(
                input_ids=batch_input_ids, attention_mask=attention_mask
            ).logits  # (batch, seq_len, vocab)

            for row, pos in enumerate(batch_positions):
                token_logits = logits[row, pos + 1]  # +1 skips <cls>
                log_probs = F.log_softmax(token_logits, dim=-1)
                M[pos] = log_probs[self._aa_token_ids].cpu().numpy()

        return M
