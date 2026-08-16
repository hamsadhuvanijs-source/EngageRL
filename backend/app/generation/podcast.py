from app.generation.base import GeneratorInterface, ProgressCallback
from app.models.chat import Chat
from app.models.material_source import MaterialSource


class PodcastGenerator(GeneratorInterface):
    mode = "podcast"

    def generate(
        self,
        chat: Chat,
        sources: list[MaterialSource],
        options: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        raise NotImplementedError("Podcast mode is not implemented yet.")
