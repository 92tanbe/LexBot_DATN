import { Fragment } from "react";

/**
 * Tách **đậm** trong một dòng thành các node React (không dùng dangerouslySetInnerHTML).
 * @param {string} line
 * @param {string} keyPrefix
 */
function lineToBoldNodes(line, keyPrefix) {
  const re = /\*\*(.+?)\*\*/g;
  const nodes = [];
  let last = 0;
  let m;
  let idx = 0;
  while ((m = re.exec(line)) !== null) {
    if (m.index > last) {
      nodes.push(
        <Fragment key={`${keyPrefix}-t-${idx++}`}>
          {line.slice(last, m.index)}
        </Fragment>
      );
    }
    nodes.push(
      <strong key={`${keyPrefix}-b-${idx++}`} className="bot-answer-strong">
        {m[1]}
      </strong>
    );
    last = m.index + m[0].length;
  }
  if (last < line.length) {
    nodes.push(
      <Fragment key={`${keyPrefix}-t-${idx++}`}>{line.slice(last)}</Fragment>
    );
  }
  return nodes.length > 0 ? nodes : [<Fragment key={`${keyPrefix}-empty`}>{line}</Fragment>];
}

/**
 * Hiển thị câu trả lời bot: khoảng cách đoạn (\n\n), xuống dòng trong đoạn (\n), **in đậm**.
 * @param {{ text?: string, variant?: 'block' | 'inline' }} props
 */
export default function BotAnswerContent({ text, variant = "block" }) {
  const raw = String(text ?? "").replace(/\r\n/g, "\n");
  const trimmed = raw.trim();
  if (!trimmed) return null;

  if (variant === "inline") {
    const lines = trimmed.split("\n");
    return (
      <span className="bot-answer-inline">
        {lines.map((line, i) => (
          <Fragment key={`inl-${i}`}>
            {i > 0 ? <br /> : null}
            {lineToBoldNodes(line, `inl-${i}`)}
          </Fragment>
        ))}
      </span>
    );
  }

  const paragraphs = trimmed
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);

  return (
    <div className="bot-answer-blocks">
      {paragraphs.map((para, pi) => {
        const lines = para.split("\n");
        return (
          <p key={`para-${pi}`} className="message-answer-p">
            {lines.map((line, li) => (
              <Fragment key={`para-${pi}-ln-${li}`}>
                {li > 0 ? <br /> : null}
                {lineToBoldNodes(line, `p-${pi}-l-${li}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
