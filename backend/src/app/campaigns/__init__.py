"""Campaign-level logic: which donors belong to a campaign, and set-level queries
over them. Deterministic Python only -- the campaign agent (later phase) calls these
as tools, and never counts, groups, or derives status itself."""
