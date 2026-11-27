-- PLN-025 restore verification: safe against partial fixtures.
-- Pipe into psql with ON_ERROR_STOP enabled by this file. Missing tables and
-- columns are reported as SKIPPED instead of aborting the drill.

\set ON_ERROR_STOP on

DO $$
DECLARE
    labels text[] := ARRAY[
        'workspace', 'project', 'issue', 'issue_comment', 'issue_activity',
        'file_asset', 'attachment', 'cycle', 'module', 'view',
        'work_item_type', 'workflow', 'workflow_transition', 'api_token'
    ];
    rel_names text[] := ARRAY[
        'workspaces', 'projects', 'issues', 'issue_comments', 'issue_activities',
        'file_assets', 'issue_attachments', 'cycles', 'modules', 'issue_views',
        'issue_types', 'workflows', 'workflow_transitions', 'api_tokens'
    ];
    orphan_specs text[] := ARRAY[
        'projects.workspace_id>workspaces.id',
        'issues.project_id>projects.id',
        'issue_comments.issue_id>issues.id',
        'issue_activities.issue_id>issues.id',
        'file_assets.workspace_id>workspaces.id',
        'file_assets.issue_id>issues.id',
        'issue_attachments.issue_id>issues.id',
        'cycles.project_id>projects.id',
        'modules.project_id>projects.id',
        'issue_views.project_id>projects.id',
        'issue_types.workspace_id>workspaces.id',
        'workflows.project_id>projects.id',
        'workflow_transitions.workflow_id>workflows.id',
        'api_tokens.workspace_id>workspaces.id'
    ];
    duplicate_specs text[] := ARRAY[
        'projects|workspace_id,identifier,deleted_at',
        'issue_types|workspace_id,key,deleted_at',
        'workflows|project_id,issue_type_id,deleted_at',
        'workflow_transitions|workflow_id,from_state_id,to_state_id,deleted_at',
        'api_tokens|token_hash'
    ];
    target regclass;
    parent regclass;
    spec text;
    parts text[];
    child_parts text[];
    parent_parts text[];
    columns text[];
    column_name text;
    total bigint;
    latest text;
    present boolean;
    usable boolean;
    i integer;
BEGIN
    RAISE NOTICE '=== PLN-025 restore verification: counts ===';
    FOR i IN 1..array_length(labels, 1) LOOP
        target := to_regclass(rel_names[i]);
        IF target IS NULL THEN
            RAISE NOTICE 'count %: SKIPPED (table absent)', labels[i];
        ELSE
            EXECUTE format('SELECT count(*) FROM %s', target) INTO total;
            RAISE NOTICE 'count %: %', labels[i], total;
        END IF;
    END LOOP;

    RAISE NOTICE '=== PLN-025 restore verification: latest created_at ===';
    FOR i IN 1..array_length(labels, 1) LOOP
        target := to_regclass(rel_names[i]);
        IF target IS NULL THEN
            RAISE NOTICE 'latest_created_at %: SKIPPED (table absent)', labels[i];
        ELSE
            SELECT EXISTS (
                SELECT 1
                FROM pg_attribute
                WHERE attrelid = target
                  AND attname = 'created_at'
                  AND NOT attisdropped
            ) INTO present;
            IF present THEN
                EXECUTE format('SELECT max(created_at)::text FROM %s', target) INTO latest;
                RAISE NOTICE 'latest_created_at %: %', labels[i], coalesce(latest, 'none');
            ELSE
                RAISE NOTICE 'latest_created_at %: SKIPPED (column absent)', labels[i];
            END IF;
        END IF;
    END LOOP;

    RAISE NOTICE '=== PLN-025 restore verification: orphan checks ===';
    FOREACH spec IN ARRAY orphan_specs LOOP
        parts := string_to_array(spec, '>');
        child_parts := string_to_array(parts[1], '.');
        parent_parts := string_to_array(parts[2], '.');
        target := to_regclass(child_parts[1]);
        parent := to_regclass(parent_parts[1]);
        IF target IS NULL OR parent IS NULL THEN
            RAISE NOTICE 'orphan %: SKIPPED (table absent)', spec;
        ELSE
            SELECT EXISTS (
                SELECT 1 FROM pg_attribute
                WHERE attrelid = target AND attname = child_parts[2] AND NOT attisdropped
            ) INTO present;
            IF present THEN
                SELECT EXISTS (
                    SELECT 1 FROM pg_attribute
                    WHERE attrelid = parent AND attname = parent_parts[2] AND NOT attisdropped
                ) INTO present;
            END IF;
            IF NOT present THEN
                RAISE NOTICE 'orphan %: SKIPPED (column absent)', spec;
            ELSE
                EXECUTE format(
                    'SELECT count(*) FROM %s c WHERE c.%I IS NOT NULL '
                    'AND NOT EXISTS (SELECT 1 FROM %s p WHERE p.%I = c.%I)',
                    target, child_parts[2], parent, parent_parts[2], child_parts[2]
                ) INTO total;
                RAISE NOTICE 'orphan %: %', spec, total;
            END IF;
        END IF;
    END LOOP;

    RAISE NOTICE '=== PLN-025 restore verification: duplicate checks ===';
    FOREACH spec IN ARRAY duplicate_specs LOOP
        parts := string_to_array(spec, '|');
        target := to_regclass(parts[1]);
        IF target IS NULL THEN
            RAISE NOTICE 'duplicate %: SKIPPED (table absent)', spec;
        ELSE
            columns := string_to_array(parts[2], ',');
            usable := true;
            FOREACH column_name IN ARRAY columns LOOP
                SELECT EXISTS (
                    SELECT 1 FROM pg_attribute
                    WHERE attrelid = target AND attname = column_name AND NOT attisdropped
                ) INTO present;
                IF NOT present THEN
                    usable := false;
                END IF;
            END LOOP;
            IF NOT usable THEN
                RAISE NOTICE 'duplicate %: SKIPPED (column absent)', spec;
            ELSE
                EXECUTE format(
                    'SELECT count(*) FROM (SELECT 1 FROM %s GROUP BY %s HAVING count(*) > 1) duplicates',
                    target, array_to_string(columns, ', ')
                ) INTO total;
                RAISE NOTICE 'duplicate %: %', spec, total;
            END IF;
        END IF;
    END LOOP;

    RAISE NOTICE '=== PLN-025 restore verification: complete ===';
END
$$;
