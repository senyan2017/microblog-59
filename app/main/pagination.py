"""Shared helpers for the paginated list pages (home feed, explore, profile,
messages, search).

Every one of those views ends up doing the same three things: read the ``page``
query-string argument, slice a result set with ``POSTS_PER_PAGE`` and build the
"newer"/"older" navigation URLs. Gathering that here keeps the views focused on
what is actually unique to each page (which query to run, which template to
render) instead of re-deriving the boilerplate every time a new list page is
added.
"""
from flask import current_app, request, url_for
from app import db


class ListPage:
    """The data a list page needs from its pagination layer.

    ``items`` are the records to render for the current page; ``prev_url`` and
    ``next_url`` point at the newer/older pages (``None`` when there is no such
    page). The trio is intentionally the same shape for database-backed and
    search-backed pages so templates can treat them identically.
    """

    def __init__(self, items, prev_url=None, next_url=None):
        self.items = items
        self.prev_url = prev_url
        self.next_url = next_url


def paginate(query, endpoint, **url_values):
    """Paginate a SQLAlchemy ``select`` for a list page.

    Reads the ``page`` argument from the request, slices ``query`` with the
    application-wide ``POSTS_PER_PAGE`` size and builds the newer/older URLs for
    ``endpoint``. Any extra ``url_values`` are forwarded to :func:`url_for` so
    routes with variable parts (for example a profile's ``username``) keep them
    on the pagination links.
    """
    page = request.args.get('page', 1, type=int)
    pagination = db.paginate(
        query, page=page, per_page=current_app.config['POSTS_PER_PAGE'],
        error_out=False)
    next_url = url_for(endpoint, page=pagination.next_num, **url_values) \
        if pagination.has_next else None
    prev_url = url_for(endpoint, page=pagination.prev_num, **url_values) \
        if pagination.has_prev else None
    return ListPage(pagination.items, prev_url=prev_url, next_url=next_url)


def paginate_search(results, total, page, endpoint, **url_values):
    """Wrap full-text search results in a :class:`ListPage`.

    Search is paginated by the search backend rather than the database, so the
    caller runs the query itself (that part is page-specific) and hands the
    ``results`` and ``total`` here to obtain the same newer/older navigation
    URLs as every other list page.
    """
    per_page = current_app.config['POSTS_PER_PAGE']
    next_url = url_for(endpoint, page=page + 1, **url_values) \
        if total > page * per_page else None
    prev_url = url_for(endpoint, page=page - 1, **url_values) \
        if page > 1 else None
    return ListPage(results, prev_url=prev_url, next_url=next_url)
