import math


class SimplePagination:
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = max(1, math.ceil(total / per_page)) if per_page else 1
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1 if self.has_prev else None
        self.next_num = page + 1 if self.has_next else None

    def iter_pages(self, left_edge=1, left_current=1, right_current=2, right_edge=1):
        last = 0
        for num in range(1, self.pages + 1):
            in_left_edge = num <= left_edge
            in_left_current = num >= self.page - left_current
            in_right_current = num <= self.page + right_current
            in_right_edge = num > self.pages - right_edge

            if in_left_edge or (in_left_current and in_right_current) or in_right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


def paginate_list(items, page, per_page):
    total = len(items)
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    current_page = min(max(page, 1), pages)
    start = (current_page - 1) * per_page
    end = start + per_page
    return SimplePagination(items[start:end], current_page, per_page, total)
