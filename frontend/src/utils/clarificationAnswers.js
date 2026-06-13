const CHOICE_INPUT_TYPES = new Set(["single_choice", "multi_choice"]);

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function getDraftItem(draft, questionId) {
  const item = draft?.[questionId];
  return isPlainObject(item)
    ? item
    : { selectedOptionIds: [], value: "", extraValues: {} };
}

function getQuestionOptions(question) {
  return Array.isArray(question?.options) ? question.options : [];
}

function hasChoiceOptions(question) {
  return (
    CHOICE_INPUT_TYPES.has(question?.input_type) ||
    (question?.input_type === "boolean" && getQuestionOptions(question).length > 0)
  );
}

function toNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function hasAnswerValue(question, item) {
  if (hasChoiceOptions(question)) {
    return Array.isArray(item.selectedOptionIds) && item.selectedOptionIds.length > 0;
  }
  if (question?.input_type === "boolean") {
    return item.value === true || item.value === false;
  }
  return item.value !== undefined && item.value !== null && String(item.value).trim() !== "";
}

function normalizeChoiceAnswer(question, item, errors) {
  const options = getQuestionOptions(question);
  const validOptionIds = new Set(options.map((option) => option.id));
  const selectedOptionIds = Array.isArray(item.selectedOptionIds)
    ? item.selectedOptionIds.filter(Boolean)
    : [];

  if (selectedOptionIds.some((optionId) => !validOptionIds.has(optionId))) {
    errors[question.id] = "Lựa chọn không hợp lệ.";
    return null;
  }

  if (question.input_type === "single_choice" && selectedOptionIds.length > 1) {
    errors[question.id] = "Chỉ chọn một phương án.";
    return null;
  }

  let value = null;
  let freeText = null;
  for (const optionId of selectedOptionIds) {
    const option = options.find((candidate) => candidate.id === optionId);
    if (!option?.requires_value) continue;

    const rawExtra = item.extraValues?.[optionId];
    if (rawExtra === undefined || rawExtra === null || String(rawExtra).trim() === "") {
      errors[question.id] = "Vui lòng nhập thêm thông tin cho lựa chọn này.";
      return null;
    }

    if (option.value_type === "number") {
      const parsed = toNumber(rawExtra);
      if (parsed === null) {
        errors[question.id] = "Vui lòng nhập số hợp lệ.";
        return null;
      }
      value = parsed;
    } else if (option.value_type === "date") {
      value = String(rawExtra);
    } else {
      freeText = String(rawExtra).trim();
    }
  }

  return {
    question_id: question.id,
    selected_option_ids: selectedOptionIds,
    value,
    free_text: freeText,
  };
}

function normalizeValueAnswer(question, item, errors) {
  if (question.input_type === "number") {
    const parsed = toNumber(item.value);
    if (parsed === null) {
      errors[question.id] = "Vui lòng nhập số hợp lệ.";
      return null;
    }
    if (typeof question.min_value === "number" && parsed < question.min_value) {
      errors[question.id] = `Giá trị tối thiểu là ${question.min_value}.`;
      return null;
    }
    if (typeof question.max_value === "number" && parsed > question.max_value) {
      errors[question.id] = `Giá trị tối đa là ${question.max_value}.`;
      return null;
    }
    return {
      question_id: question.id,
      selected_option_ids: [],
      value: parsed,
      free_text: null,
    };
  }

  if (question.input_type === "boolean") {
    return {
      question_id: question.id,
      selected_option_ids: [],
      value: item.value === true,
      free_text: null,
    };
  }

  const text = String(item.value ?? "").trim();
  return {
    question_id: question.id,
    selected_option_ids: [],
    value: question.input_type === "date" ? text : null,
    free_text: question.input_type === "date" ? null : text,
  };
}

export function getClarificationQuestions(clarification) {
  if (!isPlainObject(clarification) || !Array.isArray(clarification.questions)) {
    return [];
  }
  return clarification.questions.filter((question) => isPlainObject(question) && question.id);
}

export function createEmptyClarificationDraft(questions) {
  return Object.fromEntries(
    questions.map((question) => [
      question.id,
      { selectedOptionIds: [], value: "", extraValues: {} },
    ])
  );
}

export function validateClarificationDraft(questions, draft, options = {}) {
  const requireRequired = options.requireRequired !== false;
  const errors = {};
  const answers = [];

  for (const question of questions) {
    const item = getDraftItem(draft, question.id);
    if (!hasAnswerValue(question, item)) {
      if (question.required && requireRequired) {
        errors[question.id] = "Vui lòng trả lời câu hỏi này.";
      }
      continue;
    }

    const answer = hasChoiceOptions(question)
      ? normalizeChoiceAnswer(question, item, errors)
      : normalizeValueAnswer(question, item, errors);
    if (answer) answers.push(answer);
  }

  if (answers.length === 0 && Object.keys(errors).length === 0) {
    errors._form = "Vui lòng trả lời ít nhất một câu hỏi.";
  }

  return { ok: Object.keys(errors).length === 0, answers, errors };
}

export function sanitizeLegalChatAnswers(answers) {
  if (!Array.isArray(answers)) return [];
  return answers
    .filter((answer) => answer && typeof answer.question_id === "string")
    .map((answer) => ({
      question_id: answer.question_id,
      selected_option_ids: Array.isArray(answer.selected_option_ids)
        ? answer.selected_option_ids.filter((optionId) => typeof optionId === "string")
        : [],
      value: answer.value ?? null,
      free_text: answer.free_text ?? null,
    }));
}
