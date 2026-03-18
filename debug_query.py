import sqlite3

con = sqlite3.connect('data/doda.db')
cur = con.execute(
    """
    select o.order_no, l.url, l.last_status, l.last_checked, l.last_is_clear
    from orders o
    join links l on l.order_id = o.id
    where o.order_no in (?,?,?)
    """,
    ("673195", "635214", "676486"),
)
for r in cur.fetchall():
    print(r)
