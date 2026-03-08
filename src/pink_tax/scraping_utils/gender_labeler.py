"""Model-driven gender labeler used during scraping and cleaning."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from pink_tax.config import default_model_threshold
from pink_tax.scraping_utils.normalize import allowed_gender_values, keyword_gender_label, normalize_gender
import json
import importlib
import importlib.util
import sys

MODEL_CANDIDATE_LABELS = ["female-marketed", "male-marketed", "gender-neutral"]
MODEL_LABEL_MAP = {
    "female-marketed": "female",
    "male-marketed": "male",
    "gender-neutral": "neutral",
}


class ModelGenderLabeler:
    """Zero-shot model labeler with persistent cache and QA metadata."""

    def __init__(self, model_name: str, cache_path: Path, threshold: float = default_model_threshold):
        self.model_name = model_name
        self.cache_path = cache_path
        self.threshold = float(threshold)
        self._cache: dict[str, dict] = {}
        self._hypotheses = [f"This product is {label}." for label in MODEL_CANDIDATE_LABELS]

        try:
            torch_module = importlib.import_module("torch")
            AutoModelForSequenceClassification, AutoTokenizer = self._import_transformers_text_only()
        except ImportError as exc:
            raise SystemExit(
                "transformers + torch are required for this interpreter "
                f"({sys.executable}). Install with: "
                f"{sys.executable} -m pip install transformers torch"
            ) from exc

        try:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        except Exception as exc:
            raise SystemExit(
                f"Failed to load model '{self.model_name}'. Ensure internet access on first run "
                "or pre-download the model to local cache."
            ) from exc
        self._model.eval()
        self._torch = torch_module
        self._entailment_index = self._resolve_entailment_index()
        self._load_cache()

    @staticmethod
    def _import_transformers_text_only() -> tuple[Any, Any]:
        """Import text-model classes while masking torchvision availability."""
        original_find_spec = importlib.util.find_spec

        def patched_find_spec(name, *args, **kwargs):
            if name == "torchvision":
                return None
            return original_find_spec(name, *args, **kwargs)

        importlib.util.find_spec = patched_find_spec
        try:
            transformers_module = importlib.import_module("transformers")
            return (
                transformers_module.AutoModelForSequenceClassification,
                transformers_module.AutoTokenizer,
            )
        finally:
            importlib.util.find_spec = original_find_spec

    def _load_cache(self) -> None:
        """Load prediction cache from disk when available."""
        if not self.cache_path.exists():
            self._cache = {}
            return
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._cache = {}
            return
        self._cache = raw if isinstance(raw, dict) else {}

    def persist(self) -> None:
        """Persist cache to disk for stable and faster repeat runs."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _predict_model(self, product_name: str) -> tuple[str, float]:
        """Return model label and confidence with caching."""
        text = str(product_name or "").strip()
        if not text:
            raise ValueError("Cannot classify empty product name.")

        cached = self._cache.get(text)
        if cached and cached.get("model") == self.model_name:
            label = str(cached.get("label", ""))
            confidence = float(cached.get("confidence", 0.0))
            if label in allowed_gender_values:
                return label, confidence

        confidence_by_label = self._candidate_confidences(text)
        raw_label = max(confidence_by_label, key=lambda label: confidence_by_label[label])
        confidence = float(confidence_by_label[raw_label])
        mapped = MODEL_LABEL_MAP.get(raw_label, "")
        if mapped not in allowed_gender_values:
            raise ValueError(f"Unexpected model label '{raw_label}' for product '{text}'.")

        self._cache[text] = {
            "model": self.model_name,
            "label": mapped,
            "confidence": round(confidence, 6),
        }
        return mapped, confidence

    def _resolve_entailment_index(self) -> int:
        """Resolve entailment label index from model config."""
        label2id = getattr(self._model.config, "label2id", {}) or {}
        lowered = {str(k).lower(): int(v) for k, v in label2id.items()}
        for key, value in lowered.items():
            if "entail" in key:
                return value
        if "2" in {str(v) for v in label2id.values()}:
            return 2
        raise ValueError(
            f"Could not infer entailment index for model '{self.model_name}' "
            f"with label2id={label2id!r}"
        )

    def _candidate_confidences(self, text: str) -> dict[str, float]:
        """Score all candidate labels with NLI entailment probability."""
        premises = [text] * len(MODEL_CANDIDATE_LABELS)
        encoded = self._tokenizer(
            premises,
            self._hypotheses,
            return_tensors="pt",
            padding=True,
            truncation=True,
        )
        with self._torch.no_grad():
            logits = self._model(**encoded).logits

        if logits.ndim != 2:
            raise ValueError(f"Unexpected logits shape: {tuple(logits.shape)}")

        entailment_scores = self._torch.softmax(logits, dim=1)[:, self._entailment_index].tolist()
        total = float(sum(entailment_scores))
        if total <= 0:
            normalized = [1.0 / len(MODEL_CANDIDATE_LABELS)] * len(MODEL_CANDIDATE_LABELS)
        else:
            normalized = [float(score) / total for score in entailment_scores]
        return {label: normalized[idx] for idx, label in enumerate(MODEL_CANDIDATE_LABELS)}

    def classify(self, product_name: str, expected_label: str = "", manual_override: str = "") -> dict:
        """
        Classify one product and return final label plus QA metadata.

        Final label policy is hybrid:
        - manual override wins
        - high-confidence model decides
        - low-confidence model falls back to clear keyword label
        """
        expected = normalize_gender(expected_label) if expected_label else ""
        override = normalize_gender(manual_override) if manual_override else ""

        keyword_label, keyword_evidence = keyword_gender_label(product_name)
        model_label, model_confidence = self._predict_model(product_name)

        if override in allowed_gender_values:
            final = override
            source = "manual"
            needs_review = 0
        else:
            model_high_conf = model_confidence >= self.threshold
            keyword_clear = keyword_label in allowed_gender_values

            if model_high_conf:
                final = model_label
                if keyword_label == "conflict":
                    source = "model_conflict_keyword"
                    needs_review = 1
                elif keyword_clear and keyword_label == model_label:
                    source = "model+keyword"
                    needs_review = 0
                elif keyword_clear and keyword_label != model_label:
                    source = "model_conflict_keyword"
                    needs_review = 1
                else:
                    source = "model_only"
                    needs_review = 0
            else:
                if keyword_clear:
                    final = keyword_label
                    source = "keyword_low_model_confidence"
                    needs_review = 1
                elif keyword_label == "conflict":
                    final = model_label
                    source = "model_low_conflict_keyword"
                    needs_review = 1
                else:
                    final = model_label
                    source = "model_low_confidence"
                    needs_review = 1

        if expected and final != expected:
            needs_review = 1

        return {
            "expected_gender_label": expected,
            "keyword_gender_label": keyword_label,
            "keyword_evidence": keyword_evidence,
            "model_gender_label": model_label,
            "model_gender_confidence": round(model_confidence, 6),
            "gender_label_source": source,
            "gender_needs_review": int(needs_review),
            "gender_label": final,
            "gender_model_name": self.model_name,
            "gender_model_threshold": round(self.threshold, 4),
        }
