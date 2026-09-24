ALTER TABLE reposcope.index_generations
    ADD COLUMN chunk_count integer CHECK (chunk_count >= 0);

UPDATE reposcope.index_generations g
SET chunk_count = (
    SELECT count(*)::integer FROM reposcope.index_chunks c
    WHERE c.generation_id = g.generation_id
)
WHERE g.status IN ('ready', 'superseded');
