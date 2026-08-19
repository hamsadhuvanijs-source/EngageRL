"use client";

import { useEffect, useState } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { loadContentState, saveContentState } from "@/lib/persistence";
import type { QuizContent } from "@/types/api";

const STATE_KEY = "answers";

export function QuizView({ content, contentId }: { content: QuizContent; contentId: string }) {
  const { flushNow, reportProgress, reportQuizAnswer } = useTelemetry();
  const [answers, setAnswers] = useState<Record<number, number>>(
    () => loadContentState<Record<number, number>>(contentId, STATE_KEY) ?? {}
  );

  // Report whatever progress was already made (e.g. resuming a session) as a real completion
  // signal, not just future answers.
  useEffect(() => {
    reportProgress(Object.keys(answers).length / content.quiz.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onAnswer = (questionIndex: number, optionIndex: number) => {
    setAnswers((prev) => {
      const next = { ...prev, [questionIndex]: optionIndex };
      saveContentState(contentId, STATE_KEY, next);
      reportProgress(Object.keys(next).length / content.quiz.length);
      return next;
    });
    reportQuizAnswer(questionIndex, optionIndex === content.quiz[questionIndex].correct_index);
    void flushNow();
  };

  return (
    <>
      <h1>Quiz</h1>
      {content.quiz.map((q, qi) => {
        const selected = answers[qi];
        return (
          <div className="quiz-question" key={qi}>
            <p>
              <strong>
                {qi + 1}. {q.question}
              </strong>
            </p>
            {q.options.map((option, oi) => {
              let cls = "quiz-option";
              if (selected !== undefined) {
                if (oi === q.correct_index) cls += " correct";
                else if (oi === selected) cls += " incorrect";
              }
              return (
                <button key={oi} className={cls} onClick={() => onAnswer(qi, oi)} disabled={selected !== undefined}>
                  {option}
                </button>
              );
            })}
            {selected !== undefined && <p className="text-muted" style={{ marginTop: 8 }}>{q.explanation}</p>}
          </div>
        );
      })}
    </>
  );
}
