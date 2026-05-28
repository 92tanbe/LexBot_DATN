import BotAnswerContent from "./BotAnswerContent";

function formatClassificationLabel(classification) {
  const labels = {
    crime_candidate: "Tội danh ứng viên",
    supporting_rule: "Điều luật hỗ trợ",
    general_rule: "Quy tắc chung",
  };
  return labels[classification] || classification || "Phân tích pháp lý";
}

function formatExhibitStatus(status) {
  const labels = {
    seized: "Đã/đang bị thu giữ",
    consumed: "Đã tiêu thụ/sử dụng hết",
    not_seized: "Không thu giữ được",
    mentioned: "Có nhắc đến tang vật",
  };
  return labels[status] || status || "Chưa rõ trạng thái";
}

function formatExhibitQuantity(quantity) {
  if (!quantity || typeof quantity !== "object") return "";
  if (quantity.raw_text) return String(quantity.raw_text);
  const parts = [quantity.value, quantity.unit].filter(
    (part) => part !== undefined && part !== null && String(part).trim() !== ""
  );
  return parts.join(" ");
}

/**
 * Hiển thị phản hồi từ BLHS Graph v2 (facts.exhibits, legal_reasoning, missing_facts, citations).
 * @param {{ message: object }} props
 */
function GraphV2AnalysisPanel({ message }) {
  const exhibits = Array.isArray(message.exhibits) ? message.exhibits : [];
  const clarifyingQuestions = Array.isArray(message.clarifyingQuestions)
    ? message.clarifyingQuestions
    : [];
  const reasoning = Array.isArray(message.legalReasoning) ? message.legalReasoning : [];
  const missing = Array.isArray(message.missingFacts) ? message.missingFacts : [];
  const candidateArticles = Array.isArray(message.candidateArticles)
    ? message.candidateArticles
    : [];
  const citations = Array.isArray(message.citations) ? message.citations : [];
  const warnings = Array.isArray(message.warnings) ? message.warnings : [];
  const shouldShowExhibits =
    exhibits.length > 0 ||
    message.graphMode === "analyze" ||
    message.answerMode === "thinking" ||
    message.responseMode === "thinking";

  if (
    !shouldShowExhibits &&
    clarifyingQuestions.length === 0 &&
    reasoning.length === 0 &&
    missing.length === 0 &&
    candidateArticles.length === 0 &&
    citations.length === 0 &&
    warnings.length === 0
  ) {
    return null;
  }

  return (
    <div className="graph-v2-panel">
      {shouldShowExhibits && (
        <div className="message-section">
          <div className="message-section-title">Tang vật</div>
          {exhibits.length > 0 ? (
            <div className="exhibit-list">
              {exhibits.map((exhibit, idx) => {
                const quantityText = formatExhibitQuantity(exhibit.quantity);
                return (
                  <article key={`exhibit-${idx}`} className="exhibit-card">
                    <div className="exhibit-card-header">
                      <span className="exhibit-status">
                        {formatExhibitStatus(exhibit.status)}
                      </span>
                      {quantityText && (
                        <span className="exhibit-quantity">{quantityText}</span>
                      )}
                    </div>
                    <div className="exhibit-description">
                      {exhibit.description || "Tang vật chưa có mô tả chi tiết."}
                    </div>
                    {exhibit.source_text && (
                      <div className="exhibit-source">{exhibit.source_text}</div>
                    )}
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="exhibit-empty">Chưa nhận diện rõ tang vật</div>
          )}
        </div>
      )}

      {reasoning.length > 0 && (
        <div className="message-section">
          <div className="message-section-title">Lý luận pháp lý (Graph v2)</div>
          <div className="graph-reasoning-list">
            {reasoning.map((item, idx) => (
              <article key={`reason-${idx}`} className="graph-reasoning-card">
                <div className="graph-reasoning-header">
                  <span className="graph-reasoning-tag">
                    {formatClassificationLabel(item.classification)}
                  </span>
                  <span className="graph-reasoning-article">
                    Điều {item.article_code}
                    {item.title ? ` · ${item.title}` : ""}
                  </span>
                </div>
                {item.crime_name && (
                  <div className="graph-reasoning-crime">{item.crime_name}</div>
                )}
                {item.why_relevant && (
                  <div className="graph-reasoning-why">{item.why_relevant}</div>
                )}
                {Array.isArray(item.missing_elements) && item.missing_elements.length > 0 && (
                  <ul className="graph-reasoning-missing">
                    {item.missing_elements.map((el, elIdx) => (
                      <li key={`missing-el-${elIdx}`}>{el}</li>
                    ))}
                  </ul>
                )}
                {typeof item.confidence === "number" && (
                  <div className="graph-reasoning-confidence">
                    Độ tin cậy {Math.round(item.confidence * 100)}%
                  </div>
                )}
              </article>
            ))}
          </div>
        </div>
      )}

      {missing.length > 0 && (
        <div className="case-warning-box">
          <strong>Dữ kiện còn thiếu:</strong>
          <ul className="graph-missing-list">
            {missing.map((fact, idx) => (
              <li key={`mf-${idx}`}>{fact}</li>
            ))}
          </ul>
        </div>
      )}

      {clarifyingQuestions.length > 0 && (
        <div className="message-section">
          <div className="message-section-title">Câu hỏi cần làm rõ</div>
          <ul className="graph-detail-list">
            {clarifyingQuestions.map((question, idx) => (
              <li key={`cq-${idx}`}>{question}</li>
            ))}
          </ul>
        </div>
      )}

      {candidateArticles.length > 0 && (
        <div className="message-section">
          <div className="message-section-title">Điều luật ứng viên</div>
          <div className="candidate-article-list">
            {candidateArticles.slice(0, 8).map((article, idx) => (
              <article key={`candidate-${article.article_code || idx}`} className="candidate-article-card">
                <div className="candidate-article-top">
                  <span className="candidate-article-code">
                    Điều {article.article_code || article.article || "?"}
                  </span>
                  {typeof article.score === "number" && (
                    <span className="candidate-article-score">
                      {Math.round(article.score * 100)}%
                    </span>
                  )}
                </div>
                <div className="candidate-article-title">
                  {article.title || article.crime_name || "Chưa có tiêu đề"}
                </div>
                {article.reason && (
                  <div className="candidate-article-reason">{article.reason}</div>
                )}
              </article>
            ))}
          </div>
        </div>
      )}

      {citations.length > 0 && (
        <div className="message-section">
          <div className="message-section-title">Trích dẫn điều luật</div>
          <div className="person-analysis-meta">
            {citations.map((cite, idx) => (
              <span key={`cite-${idx}`} className="person-analysis-chip">
                {cite.article_code || cite.article
                  ? `Điều ${cite.article_code || cite.article}`
                  : "Điều luật"}
                {cite.title ? ` · ${cite.title}` : ""}
              </span>
            ))}
          </div>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="message-explanation">
          <strong>Cảnh báo:</strong> {warnings.join("; ")}
        </div>
      )}
    </div>
  );
}

export default GraphV2AnalysisPanel;
