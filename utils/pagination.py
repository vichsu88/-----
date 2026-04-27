from dataclasses import dataclass


@dataclass(frozen=True)
class Pagination:
    page: int
    per_page: int

    @property
    def skip(self):
        return (self.page - 1) * self.per_page


def parse_pagination(args, *, default_per_page=50, max_per_page=100):
    try:
        page = max(int(args.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page

    per_page = min(max(per_page, 1), max_per_page)
    return Pagination(page=page, per_page=per_page)


def page_response(results, total, pagination):
    pages = (total + pagination.per_page - 1) // pagination.per_page if total else 0
    return {
        "results": results,
        "total": total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pages,
        "has_next": pagination.page < pages,
        "has_prev": pagination.page > 1,
    }
