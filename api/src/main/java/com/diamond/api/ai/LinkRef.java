package com.diamond.api.ai;

/** A navigable result the search bar can render: a friendly label + an in-app route. */
public record LinkRef(String label, String href) {}
