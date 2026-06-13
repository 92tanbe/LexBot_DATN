import { useMemo, useState } from "react";
import {
  createEmptyClarificationDraft,
  getClarificationQuestions,
  validateClarificationDraft,
} from "../utils/clarificationAnswers";

function getInputType(question) {
  const type = question?.input_type;
  if (
    type === "single_choice" ||
    type === "multi_choice" ||
    type === "number" ||
    type === "text" ||
    type === "date" ||
    type === "boolean" ||
    type === "actor_matrix"
  ) {
    return type;
  }
  return "text";
}

function isOptionSelected(draftItem, optionId) {
  return Array.isArray(draftItem?.selectedOptionIds)
    ? draftItem.selectedOptionIds.includes(optionId)
    : false;
}

function getExtraInputType(option) {
  if (option?.value_type === "number") return "number";
  if (option?.value_type === "date") return "date";
  return "text";
}

function ClarificationForm({ clarification, disabled = false, onSubmit }) {
  const questions = useMemo(
    () => getClarificationQuestions(clarification),
    [clarification]
  );
  const questionSetId = clarification?.question_set_id || "";
  const canSubmitPartial = clarification?.can_submit_partial !== false;
  const [draft, setDraft] = useState(() => createEmptyClarificationDraft(questions));
  const [errors, setErrors] = useState({});

  if (questions.length === 0) return null;

  const updateQuestionDraft = (questionId, updater) => {
    setDraft((prev) => {
      const current = prev[questionId] || {
        selectedOptionIds: [],
        value: "",
        extraValues: {},
      };
      return { ...prev, [questionId]: updater(current) };
    });
  };

  const handleChoiceChange = (question, optionId, checked) => {
    const type = getInputType(question);
    updateQuestionDraft(question.id, (current) => {
      const currentIds = Array.isArray(current.selectedOptionIds)
        ? current.selectedOptionIds
        : [];
      const nextIds =
        type === "multi_choice"
          ? checked
            ? [...new Set([...currentIds, optionId])]
            : currentIds.filter((id) => id !== optionId)
          : [optionId];
      return { ...current, selectedOptionIds: nextIds };
    });
  };

  const handleExtraChange = (questionId, optionId, value) => {
    updateQuestionDraft(questionId, (current) => ({
      ...current,
      extraValues: { ...(current.extraValues || {}), [optionId]: value },
    }));
  };

  const handleValueChange = (questionId, value) => {
    updateQuestionDraft(questionId, (current) => ({ ...current, value }));
  };

  const handleBooleanChange = (questionId, value) => {
    updateQuestionDraft(questionId, (current) => ({ ...current, value }));
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    const result = validateClarificationDraft(questions, draft, {
      requireRequired: !canSubmitPartial,
    });
    setErrors(result.errors);
    if (!result.ok) return;
    onSubmit(result.answers);
  };

  const renderValueInput = (question, item) => {
    const type = getInputType(question);
    if (type === "number") {
      return (
        <div className="clarification-value-row">
          <input
            type="number"
            className="clarification-input"
            min={question.min_value ?? undefined}
            max={question.max_value ?? undefined}
            step="any"
            value={item.value ?? ""}
            onChange={(event) => handleValueChange(question.id, event.target.value)}
            disabled={disabled}
          />
          {question.unit ? <span className="clarification-unit">{question.unit}</span> : null}
        </div>
      );
    }

    if (type === "date") {
      return (
        <input
          type="date"
          className="clarification-input"
          value={item.value ?? ""}
          onChange={(event) => handleValueChange(question.id, event.target.value)}
          disabled={disabled}
        />
      );
    }

    if (type === "boolean") {
      return (
        <div className="clarification-option-list clarification-option-list--inline">
          <label className="clarification-option">
            <input
              type="radio"
              name={question.id}
              checked={item.value === true}
              onChange={() => handleBooleanChange(question.id, true)}
              disabled={disabled}
            />
            <span>Có</span>
          </label>
          <label className="clarification-option">
            <input
              type="radio"
              name={question.id}
              checked={item.value === false}
              onChange={() => handleBooleanChange(question.id, false)}
              disabled={disabled}
            />
            <span>Không</span>
          </label>
        </div>
      );
    }

    return (
      <textarea
        className="clarification-textarea"
        rows={type === "actor_matrix" ? 4 : 2}
        value={item.value ?? ""}
        onChange={(event) => handleValueChange(question.id, event.target.value)}
        disabled={disabled}
      />
    );
  };

  const renderChoiceInputs = (question, item) => {
    const inputType = getInputType(question) === "multi_choice" ? "checkbox" : "radio";
    return (
      <div className="clarification-option-list">
        {(question.options || []).map((option) => {
          const checked = isOptionSelected(item, option.id);
          return (
            <label key={option.id} className="clarification-option">
              <span className="clarification-option-main">
                <input
                  type={inputType}
                  name={question.id}
                  checked={checked}
                  onChange={(event) =>
                    handleChoiceChange(question, option.id, event.target.checked)
                  }
                  disabled={disabled}
                />
                <span>{option.label || option.id}</span>
              </span>
              {option.requires_value && checked ? (
                <input
                  type={getExtraInputType(option)}
                  className="clarification-input clarification-input--option"
                  value={item.extraValues?.[option.id] ?? ""}
                  placeholder={option.placeholder || "Nhập thêm"}
                  onChange={(event) =>
                    handleExtraChange(question.id, option.id, event.target.value)
                  }
                  disabled={disabled}
                />
              ) : null}
            </label>
          );
        })}
      </div>
    );
  };

  return (
    <form className="clarification-form" onSubmit={handleSubmit}>
      <div className="clarification-form-head">
        <div className="message-section-title">Bổ sung dữ kiện</div>
        {questionSetId ? <span className="clarification-set-chip">{questionSetId}</span> : null}
      </div>

      <div className="clarification-question-list">
        {questions.map((question) => {
          const item = draft[question.id] || {
            selectedOptionIds: [],
            value: "",
            extraValues: {},
          };
          const type = getInputType(question);
          const hasOptions = Array.isArray(question.options) && question.options.length > 0;
          return (
            <fieldset
              key={question.id}
              className={`clarification-question ${
                question.critical ? "clarification-question--critical" : ""
              }`}
            >
              <legend className="clarification-question-title">
                <span>{question.group || "Dữ kiện"}</span>
                {question.critical ? <span className="clarification-critical">Quan trọng</span> : null}
              </legend>
              <div className="clarification-question-text">{question.text}</div>
              {question.reason ? (
                <div className="clarification-reason">{question.reason}</div>
              ) : null}
              {Array.isArray(question.affected_articles) && question.affected_articles.length > 0 ? (
                <div className="clarification-articles">
                  {question.affected_articles.map((article) => (
                    <span key={article}>Điều {article}</span>
                  ))}
                </div>
              ) : null}

              {hasOptions && (type === "single_choice" || type === "multi_choice" || type === "boolean")
                ? renderChoiceInputs(question, item)
                : renderValueInput(question, item)}

              {errors[question.id] ? (
                <div className="clarification-error">{errors[question.id]}</div>
              ) : null}
            </fieldset>
          );
        })}
      </div>

      {errors._form ? <div className="clarification-error">{errors._form}</div> : null}

      <div className="clarification-actions">
        <button type="submit" className="clarification-submit" disabled={disabled}>
          Gửi bổ sung
        </button>
      </div>
    </form>
  );
}

export default ClarificationForm;
