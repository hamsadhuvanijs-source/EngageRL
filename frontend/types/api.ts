export interface UserOut {
  id: string;
  email: string | null;
  display_name: string | null;
  created_at: string;
}

export interface AuthResponse {
  token: string;
  user: UserOut;
}

export type SourceType = "pdf" | "txt" | "youtube" | "website" | "pasted_text";
export type Mode = "summary" | "quiz" | "flashcards" | "qa" | "flowchart" | "podcast" | "comic" | "video";

export type Difficulty = "easy" | "medium" | "hard";
export type QuestionCount = 5 | 10 | 20;

export interface QuizFlashcardsOptions {
  difficulty: Difficulty;
  num_questions: QuestionCount;
}

export interface SummaryOptions {
  length: "concise" | "detailed";
}

export interface QAOptions {
  num_questions: QuestionCount;
  answer_style: "short" | "long";
}

export interface PodcastOptions {
  length: "short" | "long";
}

export interface FlowchartOptions {
  diagram: "flowchart" | "mindmap";
}

export type GenerateOptions =
  | QuizFlashcardsOptions
  | SummaryOptions
  | QAOptions
  | PodcastOptions
  | FlowchartOptions;

export interface ChatOut {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface MaterialSourceOut {
  id: string;
  chat_id: string;
  source_type: SourceType;
  original_ref: string;
  char_count: number;
  status: "pending" | "extracted" | "failed";
  created_at: string;
  text_preview: string | null;
}

export interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

export interface SummaryContent {
  summary: string;
}

export interface QuizContent {
  quiz: QuizQuestion[];
}

export interface FlashcardsContent {
  cards: { question: string; answer: string }[];
}

export interface QAContent {
  items: { question: string; answer: string }[];
}

export interface ComicPanel {
  scene_description: string;
  dialogue: { speaker: string; text: string }[];
  caption: string | null;
  image_url: string | null;
}

export interface ComicContent {
  panels: ComicPanel[];
  image_error?: string;
}

export interface VideoScene {
  narration: string;
  duration: number;
}

export interface VideoContent {
  video_url: string;
  scenes: VideoScene[];
}

export interface PodcastSegment {
  speaker: string;
  text: string;
}

export interface PodcastHost {
  name: string;
  gender: "female" | "male";
}

export interface PodcastContent {
  title: string;
  hosts: PodcastHost[];
  segments: PodcastSegment[];
}

export interface FlowchartContent {
  title: string;
  diagram_type: "flowchart" | "mindmap";
  mermaid: string;
}

export type ModeContent =
  | SummaryContent
  | QuizContent
  | FlashcardsContent
  | QAContent
  | ComicContent
  | VideoContent
  | PodcastContent
  | FlowchartContent
  | Record<string, unknown>;

export interface GeneratedContentOut {
  id: string;
  chat_id: string;
  mode: Mode;
  status: "pending" | "ready" | "failed";
  content_json: ModeContent | null;
  options_json: Record<string, unknown> | null;
  model_used: string | null;
  progress_current: number | null;
  progress_total: number | null;
  error_message: string | null;
  created_at: string;
}

export interface ChatDetailOut {
  chat: ChatOut;
  sources: MaterialSourceOut[];
  generations: GeneratedContentOut[];
}

export type RLPolicyName = "cold_start_thompson" | "q_learning";

export interface SuggestModeOut {
  mode: Mode;
  confidence: number;
  // "cold_start_thompson" for a user's first few sessions (Thompson sampling, exploring to
  // build up real experience), "q_learning" once there's enough history for the MDP-based
  // policy to take over as the main long-term decision-maker. See backend app/rl/policy.py.
  policy: RLPolicyName;
  epsilon: number | null;
  state_key: string;
  state: Record<string, string>;
  action_scores: Record<Mode, number>;
}

export interface SessionOut {
  id: string;
  generated_content_id: string;
  started_at: string;
  completed_at: string | null;
  engagement_score: number | null;
  status: "active" | "completed" | "abandoned";
}

export interface SessionDetailOut {
  session: SessionOut;
  chat_id: string;
  mode: Mode;
  content_json: ModeContent | null;
  expected_seconds: number;
  overage_threshold_seconds: number;
}

export interface StillEngagedResponse {
  expected_seconds: number;
  overage_threshold_seconds: number;
  reading_pace_multiplier: number;
}

export interface SessionCompleteResponse {
  session: SessionOut;
  engagement_score: number;
  bandit_params: { alpha: number; beta: number };
}

export type TelemetryEventType =
  | "visibility_change"
  | "scroll"
  | "keypress"
  | "mouse_move"
  | "click"
  | "dwell"
  | "section_view"
  | "progress"
  | "enjoyment_feedback"
  | "incomplete_reason"
  | "quiz_answer";

export interface TelemetryEvent {
  event_type: TelemetryEventType;
  payload: Record<string, unknown>;
  client_ts: string;
}

export interface QTableEntryOut {
  state_key: string;
  state: Record<string, string>;
  action: Mode;
  q_value: number;
  update_count: number;
  updated_at: string;
}

export interface RLTransitionOut {
  id: string;
  chat_id: string;
  session_id: string;
  state_key: string;
  state: Record<string, string>;
  action: Mode;
  reward: number;
  next_state_key: string;
  next_state: Record<string, string>;
  done: boolean;
  policy: RLPolicyName;
  epsilon: number | null;
  created_at: string;
}

export interface PolicyStateOut {
  user_id: string;
  active_policy: RLPolicyName;
  epsilon: number | null;
  completed_sessions: number;
  cold_start_threshold: number;
  bandit_params: Record<Mode, { alpha: number; beta: number }>;
  q_table: QTableEntryOut[];
  recent_transitions: RLTransitionOut[];
}

export interface EngagementPoint {
  completed_at: string;
  engagement_score: number;
}

export interface ModePreference {
  alpha: number;
  beta: number;
  thompson_mean: number;
  q_value_avg: number | null;
  visit_count: number;
  preference: number;
}

export interface TutorMessageOut {
  id: string;
  chat_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface TutorReplyOut {
  user_message: TutorMessageOut;
  assistant_message: TutorMessageOut;
}

export interface RLPolicySummary {
  active_policy: RLPolicyName;
  completed_sessions: number;
  cold_start_threshold: number;
}

export interface StatsOut {
  chat_count: number;
  source_count: number;
  session_count: number;
  total_active_seconds: number;
  engagement_trend: EngagementPoint[];
  mode_preference: Record<Mode, ModePreference>;
  recent_chats: ChatOut[];
  rl_policy: RLPolicySummary;
}
