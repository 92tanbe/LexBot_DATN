import assert from "node:assert/strict";
import test from "node:test";

import {
  getClarificationQuestions,
  sanitizeLegalChatAnswers,
  validateClarificationDraft,
} from "./clarificationAnswers.js";

const radioQuestion = {
  id: "q_tablets_forensic_substance",
  text: "Kết luận giám định xác định hoạt chất trong hai viên nén là chất nào?",
  input_type: "single_choice",
  required: true,
  options: [
    { id: "mdma", label: "MDMA" },
    { id: "other", label: "Chất khác", requires_value: true, value_type: "text" },
  ],
};

test("builds answer payload without fact_path", () => {
  const result = validateClarificationDraft(
    [{ ...radioQuestion, fact_path: "exhibits.tablets.forensic_substance" }],
    {
      q_tablets_forensic_substance: {
        selectedOptionIds: ["mdma"],
        value: "",
        extraValues: {},
      },
    }
  );

  assert.equal(result.ok, true);
  assert.deepEqual(result.answers, [
    {
      question_id: "q_tablets_forensic_substance",
      selected_option_ids: ["mdma"],
      value: null,
      free_text: null,
    },
  ]);
  assert.equal("fact_path" in result.answers[0], false);
});

test("requires free_text when selected option needs text value", () => {
  const missing = validateClarificationDraft([radioQuestion], {
    q_tablets_forensic_substance: {
      selectedOptionIds: ["other"],
      value: "",
      extraValues: {},
    },
  });
  assert.equal(missing.ok, false);
  assert.match(missing.errors.q_tablets_forensic_substance, /nhập thêm/i);

  const filled = validateClarificationDraft([radioQuestion], {
    q_tablets_forensic_substance: {
      selectedOptionIds: ["other"],
      value: "",
      extraValues: { other: "Nimetazepam" },
    },
  });
  assert.equal(filled.ok, true);
  assert.equal(filled.answers[0].free_text, "Nimetazepam");
});

test("validates number min_value", () => {
  const question = {
    id: "q_powder_net_mass",
    text: "Khối lượng tịnh là bao nhiêu?",
    input_type: "number",
    min_value: 0,
  };

  const result = validateClarificationDraft([question], {
    q_powder_net_mass: {
      selectedOptionIds: [],
      value: "-1",
      extraValues: {},
    },
  });

  assert.equal(result.ok, false);
  assert.match(result.errors.q_powder_net_mass, /tối thiểu/i);
});

test("extracts structured questions and remains compatible with legacy response", () => {
  assert.equal(getClarificationQuestions(null).length, 0);
  assert.equal(getClarificationQuestions({ clarifying_questions: ["Legacy"] }).length, 0);
  assert.equal(
    getClarificationQuestions({ questions: [{ id: "q1", text: "A" }] }).length,
    1
  );
});

test("sanitizes answers before API submit", () => {
  const sanitized = sanitizeLegalChatAnswers([
    {
      question_id: "q1",
      selected_option_ids: ["a", 1],
      value: null,
      free_text: null,
      fact_path: "must-not-leak",
    },
  ]);

  assert.deepEqual(sanitized, [
    {
      question_id: "q1",
      selected_option_ids: ["a"],
      value: null,
      free_text: null,
    },
  ]);
});
