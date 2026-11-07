-- Vocabulary-only cutover. Stop old writers; deploy the new callers with this schema.
-- Applied V6 stays immutable. No legacy API values or configuration aliases survive.
LOCK TABLE access.organizations, links.pools, links.links, platform.command_receipts
    IN ACCESS EXCLUSIVE MODE;

-- Reproduce the existing Python sorted/ASCII JSON fingerprint, only during upgrade.
-- Receipt snapshots retain creation inputs; entropy/visibility defaults are recovered
-- by matching the old digest, never guessed. User text is not searched/replaced.
CREATE FUNCTION pg_temp.receipt_json(value jsonb) RETURNS text LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
DECLARE rendered text; escaped text := ''; character text; point integer;
BEGIN
    IF jsonb_typeof(value) = 'object' THEN
        SELECT '{' || string_agg(to_jsonb(key)::text || ': ' || pg_temp.receipt_json(item),
            ', ' ORDER BY key COLLATE "C") || '}' INTO rendered FROM jsonb_each(value) AS e(key,item);
        RETURN coalesce(rendered, '{}');
    END IF;
    rendered := value::text;
    IF jsonb_typeof(value) = 'string' THEN
        FOR position IN 1..char_length(rendered) LOOP
            character := substr(rendered, position, 1);
            point := ascii(character);
            IF point > 65535 THEN
                escaped := escaped || '\u' || lpad(to_hex(55296 + ((point - 65536) / 1024)), 4, '0')
                    || '\u' || lpad(to_hex(56320 + ((point - 65536) % 1024)), 4, '0');
            ELSIF point > 126 THEN
                escaped := escaped || '\u' || lpad(to_hex(point), 4, '0');
            ELSE
                escaped := escaped || character;
            END IF;
        END LOOP;
        RETURN escaped;
    END IF;
    RETURN rendered;
END
$$;

DO $$
DECLARE receipt record; snapshot jsonb; payload jsonb; level text; visibility text;
    matched boolean;
BEGIN
    FOR receipt IN SELECT ctid, * FROM platform.command_receipts
        WHERE action IN ('ReservePoolCommand', 'CreateLinkCommand')
        AND result #>> '{value,visibility}' = 'workload_private'
        AND expires_at > clock_timestamp()
    LOOP
        snapshot := receipt.result -> 'value';
        matched := false;
        FOREACH level IN ARRAY ARRAY[NULL, 'high'] LOOP
            FOREACH visibility IN ARRAY ARRAY[NULL, 'workload_private'] LOOP
                IF receipt.action = 'ReservePoolCommand' THEN
                    payload := jsonb_build_object('size', snapshot->'size', 'name', snapshot->'name',
                        'entropy', level, 'visibility', visibility);
                ELSE
                    payload := jsonb_build_object('draft', jsonb_build_object(
                        'destination_url', snapshot->'destination_url', 'title', snapshot->'title',
                        'notes', snapshot->'notes', 'pool_id', snapshot->'pool_id', 'short_code', NULL,
                        'entropy', level, 'visibility', visibility));
                END IF;
                IF encode(sha256(convert_to(pg_temp.receipt_json(payload), 'UTF8')), 'hex') = receipt.fingerprint THEN
                    matched := true;
                    IF visibility IS NOT NULL THEN
                        payload := jsonb_set(payload,
                            CASE WHEN receipt.action = 'ReservePoolCommand' THEN ARRAY['visibility']
                                ELSE ARRAY['draft','visibility'] END, '"client_private"');
                        UPDATE platform.command_receipts SET fingerprint =
                            encode(sha256(convert_to(pg_temp.receipt_json(payload), 'UTF8')), 'hex')
                            WHERE ctid = receipt.ctid;
                    END IF;
                END IF;
            END LOOP;
        END LOOP;
        IF NOT matched THEN
            RAISE EXCEPTION 'Cannot migrate a live private receipt fingerprint; upgrade rolled back';
        END IF;
    END LOOP;
END
$$;
DROP FUNCTION pg_temp.receipt_json(jsonb);

ALTER TABLE access.organizations RENAME COLUMN workloads TO private_clients;
ALTER TABLE access.organizations RENAME CONSTRAINT organizations_workloads_check TO organizations_private_clients_check;
ALTER TABLE links.pools DISABLE TRIGGER pools_policy;
ALTER TABLE links.links DISABLE TRIGGER links_policy;
ALTER TABLE links.pools DROP CONSTRAINT pools_visibility_check, DROP CONSTRAINT pools_check;
ALTER TABLE links.links DROP CONSTRAINT links_visibility_check, DROP CONSTRAINT links_check1;

UPDATE links.pools SET visibility = 'client_private' WHERE visibility = 'workload_private';
UPDATE links.links SET visibility = 'client_private' WHERE visibility = 'workload_private';
UPDATE platform.command_receipts SET result = jsonb_set(result, '{value,visibility}', '"client_private"')
    WHERE result #>> '{value,visibility}' = 'workload_private';

ALTER TABLE links.pools ADD CONSTRAINT pools_visibility_check CHECK (visibility IN ('organization', 'client_private')),
    ADD CONSTRAINT pools_check CHECK (visibility <> 'client_private' OR (entropy IS NOT DISTINCT FROM 'high' AND owner_issuer IS NOT NULL AND owner_client IS NOT NULL));
ALTER TABLE links.links ADD CONSTRAINT links_visibility_check CHECK (visibility IN ('organization', 'client_private')),
    ADD CONSTRAINT links_check1 CHECK (visibility <> 'client_private' OR (entropy IS NOT DISTINCT FROM 'high' AND owner_issuer IS NOT NULL AND owner_client IS NOT NULL));

CREATE OR REPLACE FUNCTION links.guard_policy() RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog
AS $$
DECLARE pool links.pools;
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.owner_issuer := CASE WHEN NEW.visibility = 'client_private'
            THEN nullif(current_setting('plazia.issuer', true), '') END;
        NEW.owner_client := CASE WHEN NEW.visibility = 'client_private'
            THEN nullif(current_setting('plazia.client_id', true), '') END;
    END IF;
    IF TG_OP = 'UPDATE' AND
       ROW(OLD.entropy, OLD.visibility, OLD.owner_issuer, OLD.owner_client) IS DISTINCT FROM
       ROW(NEW.entropy, NEW.visibility, NEW.owner_issuer, NEW.owner_client) THEN
        RAISE check_violation USING MESSAGE = 'Issued link policy is immutable';
    END IF;
    IF TG_TABLE_NAME = 'links' THEN
        IF NEW.pool_id IS NOT NULL THEN
            SELECT * INTO pool FROM links.pools WHERE id = NEW.pool_id AND organization_id = NEW.organization_id FOR SHARE;
            IF NOT FOUND OR ROW(pool.entropy, pool.visibility, pool.owner_issuer, pool.owner_client) IS DISTINCT FROM
                ROW(NEW.entropy, NEW.visibility, NEW.owner_issuer, NEW.owner_client) THEN
                RAISE check_violation USING MESSAGE = 'Link policy must match its pool';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END
$$;
ALTER TABLE links.pools ENABLE TRIGGER pools_policy;
ALTER TABLE links.links ENABLE TRIGGER links_policy;
ALTER POLICY links_workload_scope ON links.links RENAME TO links_client_scope;
ALTER POLICY pools_workload_scope ON links.pools RENAME TO pools_client_scope;
ALTER POLICY statistics_workload_scope ON links.statistics RENAME TO statistics_client_scope;
ALTER POLICY receipts_workload_scope ON platform.command_receipts RENAME TO receipts_client_scope;
