from enum import Enum

from models.baseline_fill_mask_model import FillMaskModel
from models.baseline_generation_model import GenerationModel
from models.baseline_llama_3_chat_model import Llama3ChatModel
from models.dual_llama_3_model import Llama3DualPrompt


class Models(Enum):
    BASELINE_FILL_MASK = "baseline_fill_mask"
    BASELINE_GENERATION = "baseline_generation"
    BASELINE_LLAMA_3_CHAT = "baseline_llama_3_chat"
    DUAL_LLAMA_3 = "dual_llama_3_chat"

    # Add more models here

    @staticmethod
    def get_model(model_name: str):
        model = Models(model_name)
        if model == Models.BASELINE_FILL_MASK:
            return FillMaskModel
        elif model == Models.BASELINE_GENERATION:
            return GenerationModel
        elif model == Models.BASELINE_LLAMA_3_CHAT:
            return Llama3ChatModel
        elif model == Models.DUAL_LLAMA_3:
            return Llama3DualPrompt
        else:
            raise ValueError(f"Model `{model_name}` not found.")
