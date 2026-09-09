from app.generation.base import ProgressCallback, TextGenerator
from app.generation.gemini_client import BACKGROUND_TRANSIENT_SERVER_RETRIES
from app.models.chat import Chat
from app.models.material_source import MaterialSource

# Two distinct shapes, picked by the user's "diagram" option. Both ask Gemini for raw Mermaid
# syntax (see FlowchartView on the frontend, which renders it with mermaid.js) — the strict
# per-syntax rules matter because a single malformed line makes mermaid fail to render the whole
# diagram, and the model is far more reliable when the grammar is spelled out than when asked
# for "a flowchart" in the abstract.
FLOWCHART_PROMPT = """You are a study assistant that turns material into a clear Mermaid.js flowchart. Given \
study material (possibly from multiple sources), produce a JSON object with:
- "title": a short title for the diagram
- "diagram_type": the exact string "flowchart"
- "mermaid": a single string of valid Mermaid flowchart syntax that maps out the material as a process / \
decision / cause-and-effect flow.

Mermaid rules you MUST follow exactly:
- First line is exactly: flowchart TD
- 10-18 nodes. Give every node a short alphanumeric id (n1, n2, ...) and a quoted label: n1["Photosynthesis"]
- Node labels: keep under 8 words, wrap in double quotes, no line breaks, no unescaped double quotes inside.
- Edges: n1 --> n2, or with a label: n1 -->|"yes"| n2
- For a decision use a rhombus node: n3{"Is it dark?"}
- Do NOT use styling, classDef, click, subgraph, or HTML. Just nodes and edges.
- Every node must be connected to at least one other node; the graph should read top to bottom.

Respond with ONLY the JSON object, no markdown fences, no commentary."""

MINDMAP_PROMPT = """You are a study assistant that turns material into a Mermaid.js mindmap. Given study \
material (possibly from multiple sources), produce a JSON object with:
- "title": a short title for the diagram
- "diagram_type": the exact string "mindmap"
- "mermaid": a single string of valid Mermaid mindmap syntax summarizing the material as a hierarchy.

Mermaid rules you MUST follow exactly:
- First line is exactly: mindmap
- Second line is the root: one indent level (2 spaces) then root((Central Topic)) with the actual topic name.
- Children are deeper indentation, ALWAYS in steps of exactly 2 spaces per level. Never jump more than one \
level deeper than the parent.
- 3-6 top-level branches, each with 2-5 child nodes, up to 3 levels deep total.
- Each node is plain text only (no brackets, no quotes, no punctuation like () [] {} : ; ), under 6 words.
- Do NOT use icons, classes, markdown, or styling.

Respond with ONLY the JSON object, no markdown fences, no commentary."""

PROMPTS = {"flowchart": FLOWCHART_PROMPT, "mindmap": MINDMAP_PROMPT}
DEFAULT_DIAGRAM = "flowchart"


class FlowchartGenerator(TextGenerator):
    mode = "flowchart"
    # The frontend shows a simulated (time-estimated) progress bar for this mode rather than a
    # bare "Working...", so it's fine to ride out a longer Gemini demand spike (503 UNAVAILABLE)
    # here instead of failing fast the way the plain text modes do.
    max_retries = BACKGROUND_TRANSIENT_SERVER_RETRIES

    def build_system_prompt(self, options: dict | None) -> str:
        options = options or {}
        diagram = options.get("diagram") if options.get("diagram") in PROMPTS else DEFAULT_DIAGRAM
        return PROMPTS[diagram]

    def generate(
        self,
        chat: Chat,
        sources: list[MaterialSource],
        options: dict | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> dict:
        payload = super().generate(chat, sources, options, on_progress)
        mermaid = str(payload.get("mermaid") or "").strip()
        if not mermaid:
            raise ValueError("The model did not return any Mermaid diagram syntax.")
        options = options or {}
        payload["mermaid"] = mermaid
        payload.setdefault(
            "diagram_type",
            options.get("diagram") if options.get("diagram") in PROMPTS else DEFAULT_DIAGRAM,
        )
        return payload
