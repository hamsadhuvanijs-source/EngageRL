"""Single source of truth for the RL action space.

An "action" is a learning format the agent can choose to present to the learner. This must
stay in lockstep with what the generation pipeline can actually produce — flowchart/podcast
exist as stubbed generators (`NotImplementedError`) and are deliberately excluded here so the
policy (cold-start Thompson sampling or Q-learning) can never select an action that would just
501 when acted on.

When a new format's generator is implemented, add it here and it automatically becomes
available to both the cold-start bandit and the Q-learning policy.
"""

IMPLEMENTED_MODES: tuple[str, ...] = ("summary", "quiz", "flashcards", "qa", "comic", "video")
