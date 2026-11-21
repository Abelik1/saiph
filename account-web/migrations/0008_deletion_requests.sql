-- Account deletion requests from /account/delete (Google Play User Data policy).
-- One row per signed-in account: repeating a pending request keeps the first
-- time. The owner marks a request done once the account and data are removed.
CREATE TABLE saiph_billing.deletion_requests (
    stripe_account_id text NOT NULL CHECK (stripe_account_id ~ '^acct_[A-Za-z0-9]+$'),
    auth_subject text NOT NULL CHECK (length(auth_subject) BETWEEN 1 AND 255),
    auth_issuer text NOT NULL CHECK (auth_issuer ~ '^https://[a-z0-9.-]+/$' AND length(auth_issuer) <= 255),
    requested_at bigint NOT NULL CHECK (requested_at > 0),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'done')),
    completed_at bigint CHECK (completed_at IS NULL OR completed_at >= requested_at),
    CHECK ((state = 'done') = (completed_at IS NOT NULL)),
    PRIMARY KEY (stripe_account_id, auth_subject)
);
CREATE INDEX deletion_requests_pending
    ON saiph_billing.deletion_requests (stripe_account_id, requested_at)
    WHERE state = 'pending';
