from app.generation.base import GeneratorInterface, ProgressCallback
from app.models.chat import Chat
from app.models.material_source import MaterialSource


class FlowchartGenerator(GeneratorInterface):
    mode = "flowchart"

    def generate(
        self,
        chat: Chat,
        sources: list[MaterialSource],
        options: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        raise NotImplementedError("Flowchart mode is not implemented yet.")
