import BotAnswerContent from "./BotAnswerContent";

function formatClassificationLabel(classification) {
  const labels = {
    crime_candidate: "Tội danh ứng viên",
    supporting_rule: "Điều luật hỗ trợ",
    general_rule: "Quy tắc chung",
  };
  return labels[classification] || classification || "Phân tích pháp lý";
}

/**
 * Hiển thị phản hồi từ BLHS Graph v2 (legal_reasoning, missing_facts, citations).
 * @param {{ message: object }} props
 */
function GraphV2AnalysisPanel({ message }) {
  const reasoning = Array.isArray(message.legalReasoning) ? message.legalReasoning : [];
  const missing = Array.isArray(message.missingFacts) ? message.missingFacts : [];
  const citations = Array.isArray(message.citations) ? message.citations : [];
  const warnings = Array.isArray(message.warnings) ? message.warnings : [];

  if (
    reasoning.length === 0 &&
    missing.length === 0 &&
    citations.length === 0 &&
    warnings.length === 0
  ) {
    return null;
  }

  return (
    <div className="graph-v2-panel">
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
