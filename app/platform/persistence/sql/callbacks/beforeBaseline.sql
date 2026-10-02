DO $$
BEGIN
    RAISE EXCEPTION 'Links baselining is unsupported; use a fresh Flyway target';
END
$$;
