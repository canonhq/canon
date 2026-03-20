-- ParadeDB BM25 full-text index (optional — requires pg_search extension)
CREATE EXTENSION IF NOT EXISTS pg_search;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'idx_spec_sections_bm25'
    ) THEN
        CALL paradedb.create_bm25(
            index_name   => 'idx_spec_sections_bm25',
            table_name   => 'spec_sections',
            key_field    => 'id',
            text_fields  => paradedb.field('heading') || paradedb.field('body')
        );
    END IF;
END
$$;
