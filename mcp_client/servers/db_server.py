"""Day 25: 数据库查询 MCP Server（只读）。"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Database")


@mcp.tool()
def query_readonly(db_path: str, sql: str) -> str:
    """执行只读 SQL 查询。

    IMPORTANT: 只允许 SELECT 语句。任何写操作会被拒绝。

    Args:
        db_path: SQLite 数据库文件路径。
        sql: SELECT 查询语句。
    """
    # 安全检查：只允许 SELECT
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT"):
        return "ERROR: 只允许 SELECT 查询"

    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"]
    for kw in forbidden:
        if kw in sql_stripped:
            return f"ERROR: 禁止的 SQL 关键词: {kw}"

    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "(查询结果为空)"

        # 格式化输出
        headers = rows[0].keys()
        lines = [" | ".join(headers)]
        lines.append("-" * len(lines[0]))
        for row in rows[:50]:
            lines.append(" | ".join(str(row[h]) for h in headers))
        if len(rows) > 50:
            lines.append(f"... 共 {len(rows)} 行")
        return "\n".join(lines)
    except Exception as e:
        return f"查询失败: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
