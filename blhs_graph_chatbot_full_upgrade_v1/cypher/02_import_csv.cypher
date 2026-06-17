LOAD CSV WITH HEADERS FROM 'file:///laws.csv' AS row
MERGE (n:Law {id: row.id})
SET n.code=row.code, n.title=row.title, n.source_file=row.source_file, n.description=row.description;

LOAD CSV WITH HEADERS FROM 'file:///parts.csv' AS row
MERGE (n:Part {id: row.id})
SET n.part_id=row.part_id, n.name=row.name
WITH row, n MATCH (law:Law {id: row.law_id}) MERGE (law)-[:HAS_PART]->(n);

LOAD CSV WITH HEADERS FROM 'file:///chapters.csv' AS row
MERGE (n:Chapter {id: row.id})
SET n.chapter_id=row.chapter_id, n.name=row.name
WITH row, n MATCH (p:Part {id: row.part_node_id}) MERGE (p)-[:HAS_CHAPTER]->(n);

LOAD CSV WITH HEADERS FROM 'file:///sections.csv' AS row
MERGE (n:Section {id: row.id})
SET n.section_id=row.section_id, n.name=row.name
WITH row, n MATCH (ch:Chapter {id: row.chapter_node_id}) MERGE (ch)-[:HAS_SECTION]->(n);

LOAD CSV WITH HEADERS FROM 'file:///articles.csv' AS row
MERGE (n:Article {id: row.id})
SET n.article_code=row.article_code,
    n.article_number=CASE WHEN row.article_number = '' THEN null ELSE toInteger(row.article_number) END,
    n.article_suffix=CASE WHEN row.article_suffix = '' THEN null ELSE row.article_suffix END,
    n.title=row.title, n.full_text=row.full_text, n.status=row.status,
    n.page_start=CASE WHEN row.page_start = '' THEN null ELSE toInteger(row.page_start) END,
    n.page_end=CASE WHEN row.page_end = '' THEN null ELSE toInteger(row.page_end) END,
    n.source_file=row.source_file, n.part_name=row.part_name, n.chapter_name=row.chapter_name, n.section_name=row.section_name,
    n.normalized_text=row.normalized_text
WITH row, n
OPTIONAL MATCH (ch:Chapter {id: row.chapter_node_id})
FOREACH (_ IN CASE WHEN ch IS NULL THEN [] ELSE [1] END | MERGE (ch)-[:HAS_ARTICLE]->(n))
WITH row, n
OPTIONAL MATCH (s:Section {id: row.section_node_id})
FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END | MERGE (s)-[:HAS_ARTICLE]->(n));

LOAD CSV WITH HEADERS FROM 'file:///clauses.csv' AS row
MERGE (n:Clause {id: row.id})
SET n.article_code=row.article_code,
    n.clause_no=CASE WHEN row.clause_no = '' THEN null ELSE toInteger(row.clause_no) END,
    n.text=row.text, n.role=row.role, n.normalized_text=row.normalized_text
WITH row, n MATCH (a:Article {id: row.article_id}) MERGE (a)-[:HAS_CLAUSE]->(n);

LOAD CSV WITH HEADERS FROM 'file:///points.csv' AS row
MERGE (n:Point {id: row.id})
SET n.article_code=row.article_code,
    n.clause_no=CASE WHEN row.clause_no = '' THEN null ELSE toInteger(row.clause_no) END,
    n.point=row.point, n.text=row.text, n.role=row.role, n.normalized_text=row.normalized_text
WITH row, n MATCH (c:Clause {id: row.clause_id}) MERGE (c)-[:HAS_POINT]->(n);

LOAD CSV WITH HEADERS FROM 'file:///conditions.csv' AS row
MERGE (n:Condition {id: row.id})
SET n.article_code=row.article_code, n.condition_type=row.condition_type, n.text=row.text,
    n.normalized_text=row.normalized_text, n.required=(row.required = 'true')
WITH row, n
OPTIONAL MATCH (c:Clause {id: row.owner_id}) WHERE row.owner_kind = 'Clause'
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:HAS_CONDITION]->(n))
WITH row, n
OPTIONAL MATCH (p:Point {id: row.owner_id}) WHERE row.owner_kind = 'Point'
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:HAS_CONDITION]->(n));

LOAD CSV WITH HEADERS FROM 'file:///penalty_frames.csv' AS row
MERGE (n:PenaltyFrame {id: row.id})
SET n.article_code=row.article_code, n.penalty_type=row.penalty_type,
    n.min_imprisonment_months=CASE WHEN row.min_imprisonment_months = '' THEN null ELSE toInteger(row.min_imprisonment_months) END,
    n.max_imprisonment_months=CASE WHEN row.max_imprisonment_months = '' THEN null ELSE toInteger(row.max_imprisonment_months) END,
    n.fine_min_vnd=CASE WHEN row.fine_min_vnd = '' THEN null ELSE toInteger(row.fine_min_vnd) END,
    n.fine_max_vnd=CASE WHEN row.fine_max_vnd = '' THEN null ELSE toInteger(row.fine_max_vnd) END,
    n.has_life_imprisonment=(row.has_life_imprisonment = 'true'),
    n.has_death_penalty=(row.has_death_penalty = 'true'),
    n.text=row.text
WITH row, n
OPTIONAL MATCH (c:Clause {id: row.owner_id}) WHERE row.owner_kind = 'Clause'
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:HAS_PENALTY_FRAME]->(n))
WITH row, n
OPTIONAL MATCH (p:Point {id: row.owner_id}) WHERE row.owner_kind = 'Point'
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:HAS_PENALTY_FRAME]->(n));

LOAD CSV WITH HEADERS FROM 'file:///crimes.csv' AS row
MERGE (n:Crime {id: row.id})
SET n.article_code=row.article_code, n.name=row.name, n.crime_group=row.crime_group, n.status=row.status, n.normalized_name=row.normalized_name
WITH row, n MATCH (a:Article {id: row.article_id}) MERGE (a)-[:DEFINES_CRIME]->(n);

LOAD CSV WITH HEADERS FROM 'file:///rules.csv' AS row
MERGE (n:Rule {id: row.id})
SET n.article_code=row.article_code,
    n.clause_no=CASE WHEN row.clause_no = '' THEN null ELSE toInteger(row.clause_no) END,
    n.point=row.point, n.text=row.text, n.rule_type=row.rule_type,
    n.priority=CASE WHEN row.priority = '' THEN null ELSE toInteger(row.priority) END,
    n.normalized_text=row.normalized_text
WITH row, n
MATCH (a:Article {id: row.article_id}) MERGE (a)-[:HAS_RULE]->(n)
WITH row, n
OPTIONAL MATCH (c:Clause {id: row.owner_id}) WHERE row.owner_kind = 'Clause'
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:REPRESENTS_RULE]->(n))
WITH row, n
OPTIONAL MATCH (p:Point {id: row.owner_id}) WHERE row.owner_kind = 'Point'
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:REPRESENTS_RULE]->(n));

MATCH (r:Rule), (c:Condition)
WHERE r.owner_id IS NOT NULL AND c.id STARTS WITH 'condition_' AND c.id CONTAINS replace(r.owner_id, 'article_', 'article_') AND c.article_code = r.article_code
MERGE (r)-[:HAS_CONDITION]->(c);

LOAD CSV WITH HEADERS FROM 'file:///penalties.csv' AS row
MERGE (n:Penalty {id: row.id})
SET n.role=row.role, n.penalty_type=row.penalty_type, n.text=row.text,
    n.min_imprisonment_months=CASE WHEN row.min_imprisonment_months = '' THEN null ELSE toInteger(row.min_imprisonment_months) END,
    n.max_imprisonment_months=CASE WHEN row.max_imprisonment_months = '' THEN null ELSE toInteger(row.max_imprisonment_months) END,
    n.fine_min_vnd=CASE WHEN row.fine_min_vnd = '' THEN null ELSE toInteger(row.fine_min_vnd) END,
    n.fine_max_vnd=CASE WHEN row.fine_max_vnd = '' THEN null ELSE toInteger(row.fine_max_vnd) END,
    n.has_life_imprisonment=(row.has_life_imprisonment = 'true'),
    n.has_death_penalty=(row.has_death_penalty = 'true')
WITH row, n MATCH (pf:PenaltyFrame {id: row.penalty_frame_id})
FOREACH (_ IN CASE WHEN row.role = 'main' THEN [1] ELSE [] END | MERGE (pf)-[:HAS_MAIN_PENALTY]->(n))
FOREACH (_ IN CASE WHEN row.role = 'additional' THEN [1] ELSE [] END | MERGE (pf)-[:HAS_ADDITIONAL_PENALTY]->(n));

LOAD CSV WITH HEADERS FROM 'file:///legal_concepts.csv' AS row
MERGE (n:LegalConcept {id: row.id})
SET n.name=row.name, n.concept_type=row.concept_type, n.article_code=row.article_code, n.description=row.description, n.normalized_name=row.normalized_name
WITH row, n
OPTIONAL MATCH (a:Article {id: row.article_id})
FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | MERGE (a)-[:HAS_LEGAL_CONCEPT]->(n));

LOAD CSV WITH HEADERS FROM 'file:///mitigating_factors.csv' AS row
MERGE (n:MitigatingFactor {id: row.id})
SET n.article_code=row.article_code, n.point=row.point, n.text=row.text, n.normalized_text=row.normalized_text
WITH row, n MATCH (a:Article {id: row.article_id}) MERGE (a)-[:HAS_MITIGATING_FACTOR]->(n);

LOAD CSV WITH HEADERS FROM 'file:///aggravating_factors.csv' AS row
MERGE (n:AggravatingFactor {id: row.id})
SET n.article_code=row.article_code, n.point=row.point, n.text=row.text, n.normalized_text=row.normalized_text
WITH row, n MATCH (a:Article {id: row.article_id}) MERGE (a)-[:HAS_AGGRAVATING_FACTOR]->(n);

LOAD CSV WITH HEADERS FROM 'file:///subject_requirements.csv' AS row
MERGE (n:SubjectRequirement {id: row.id})
SET n.article_code=row.article_code, n.requirement_type=row.requirement_type, n.text=row.text, n.normalized_text=row.normalized_text
WITH row, n MATCH (c:Crime {id: row.crime_id}) MERGE (c)-[:HAS_SUBJECT_REQUIREMENT]->(n);

LOAD CSV WITH HEADERS FROM 'file:///object_requirements.csv' AS row
MERGE (n:ObjectRequirement {id: row.id})
SET n.article_code=row.article_code, n.requirement_type=row.requirement_type, n.text=row.text, n.normalized_text=row.normalized_text
WITH row, n MATCH (c:Crime {id: row.crime_id}) MERGE (c)-[:HAS_OBJECT_REQUIREMENT]->(n);

LOAD CSV WITH HEADERS FROM 'file:///act_requirements.csv' AS row
MERGE (n:ActRequirement {id: row.id})
SET n.article_code=row.article_code, n.requirement_type=row.requirement_type, n.text=row.text, n.normalized_text=row.normalized_text
WITH row, n MATCH (c:Crime {id: row.crime_id}) MERGE (c)-[:HAS_ACT_REQUIREMENT]->(n);

LOAD CSV WITH HEADERS FROM 'file:///consequence_requirements.csv' AS row
MERGE (n:ConsequenceRequirement {id: row.id})
SET n.article_code=row.article_code, n.requirement_type=row.requirement_type, n.text=row.text, n.normalized_text=row.normalized_text
WITH row, n MATCH (c:Crime {id: row.crime_id}) MERGE (c)-[:HAS_CONSEQUENCE_REQUIREMENT]->(n);

LOAD CSV WITH HEADERS FROM 'file:///quantity_thresholds.csv' AS row
MERGE (n:QuantityThreshold {id: row.id})
SET n.article_code=row.article_code, n.text=row.text,
    n.min_value=CASE WHEN row.min_value = '' THEN null ELSE toFloat(row.min_value) END,
    n.max_value=CASE WHEN row.max_value = '' THEN null ELSE toFloat(row.max_value) END,
    n.unit=row.unit, n.normalized_text=row.normalized_text
WITH row, n MATCH (c:Crime {id: row.crime_id}) MERGE (c)-[:HAS_QUANTITY_THRESHOLD]->(n)
WITH row, n
OPTIONAL MATCH (cond:Condition {id: row.owner_id}) WHERE row.owner_kind = 'Condition'
FOREACH (_ IN CASE WHEN cond IS NULL THEN [] ELSE [1] END | MERGE (cond)-[:HAS_QUANTITY_THRESHOLD]->(n));

LOAD CSV WITH HEADERS FROM 'file:///exceptions.csv' AS row
MERGE (n:Exception {id: row.id})
SET n.article_code=row.article_code, n.exception_type=row.exception_type, n.text=row.text, n.normalized_text=row.normalized_text
WITH row, n MATCH (a:Article {id: row.article_id}) MERGE (a)-[:HAS_EXCEPTION]->(n);


LOAD CSV WITH HEADERS FROM 'file:///judicial_measures.csv' AS row
MERGE (n:JudicialMeasure {id: row.id})
SET n.article_code=row.article_code, n.name=row.name, n.text=row.text
WITH row, n MATCH (a:Article {id: row.article_id}) MERGE (a)-[:HAS_JUDICIAL_MEASURE]->(n);

LOAD CSV WITH HEADERS FROM 'file:///references.csv' AS row
MERGE (n:Reference {id: row.id})
SET n.from_id=row.from_id, n.from_label=row.from_label, n.from_article_code=row.from_article_code, n.to_article_code=row.to_article_code, n.text=row.text
WITH row, n
OPTIONAL MATCH (fromA:Article {id: row.from_article_id})
FOREACH (_ IN CASE WHEN fromA IS NULL THEN [] ELSE [1] END | MERGE (fromA)-[:HAS_REFERENCE]->(n))
WITH row, n
OPTIONAL MATCH (toA:Article {article_code: row.to_article_code})
FOREACH (_ IN CASE WHEN toA IS NULL THEN [] ELSE [1] END | MERGE (n)-[:TARGETS]->(toA))
WITH row
OPTIONAL MATCH (fromA:Article {id: row.from_article_id})
OPTIONAL MATCH (toA:Article {article_code: row.to_article_code})
FOREACH (_ IN CASE WHEN fromA IS NULL OR toA IS NULL THEN [] ELSE [1] END | MERGE (fromA)-[:REFERENCES]->(toA));

LOAD CSV WITH HEADERS FROM 'file:///legal_signals.csv' AS row
MERGE (n:LegalSignal {id: row.id}) SET n.name=row.name, n.signal_type=row.signal_type, n.description=row.description;

LOAD CSV WITH HEADERS FROM 'file:///signal_article_links.csv' AS row
MATCH (s:LegalSignal {id: row.signal_id})
OPTIONAL MATCH (a:Article {article_code: row.article_code})
FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | MERGE (s)-[:RELATED_TO]->(a));

LOAD CSV WITH HEADERS FROM 'file:///substances.csv' AS row
MERGE (n:Substance {id: row.id}) SET n.name=row.name, n.substance_type=row.substance_type, n.notes=row.notes;

LOAD CSV WITH HEADERS FROM 'file:///substance_aliases.csv' AS row
MERGE (n:SubstanceAlias {id: row.id}) SET n.text=row.text, n.normalized_to=row.normalized_to
WITH row, n MATCH (s:Substance {id: row.substance_id}) MERGE (n)-[:NORMALIZES_TO]->(s);

LOAD CSV WITH HEADERS FROM 'file:///slang_terms.csv' AS row
MERGE (n:SlangTerm {id: row.id}) SET n.text=row.text, n.normalized_to=row.normalized_to, n.category=row.category
WITH row, n
OPTIONAL MATCH (sig:LegalSignal {id: row.signal_id})
FOREACH (_ IN CASE WHEN sig IS NULL THEN [] ELSE [1] END | MERGE (n)-[:MAY_INDICATE]->(sig))
WITH row, n
OPTIONAL MATCH (lc:LegalConcept {id: row.concept_id})
FOREACH (_ IN CASE WHEN lc IS NULL THEN [] ELSE [1] END | MERGE (n)-[:NORMALIZES_TO]->(lc))
WITH row, n
OPTIONAL MATCH (sub:Substance {id: row.substance_id})
FOREACH (_ IN CASE WHEN sub IS NULL THEN [] ELSE [1] END | MERGE (n)-[:NORMALIZES_TO]->(sub));

LOAD CSV WITH HEADERS FROM 'file:///action_aliases.csv' AS row
MERGE (n:ActionAlias {id: row.id}) SET n.text=row.text, n.normalized_to=row.normalized_to
WITH row, n MATCH (s:LegalSignal {id: row.signal_id}) MERGE (n)-[:MAY_INDICATE]->(s);
