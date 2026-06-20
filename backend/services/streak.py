def get_team_streak(conn, team_id: int, before_date):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT home_team_id, away_team_id, home_score, away_score
        FROM games
        WHERE (home_team_id = %s OR away_team_id = %s)
          AND status = 'final'
          AND home_score IS NOT NULL
          AND away_score IS NOT NULL
          AND game_date < %s
        ORDER BY game_date DESC
        """,
        (team_id, team_id, before_date),
    )
    rows = cur.fetchall()
    cur.close()

    if not rows:
        return {"streak_type": None, "streak_count": 0, "streak_label": "-"}

    def won(row):
        home_team_id, away_team_id, home_score, away_score = row
        if home_team_id == team_id:
            return home_score > away_score
        return away_score > home_score

    streak_type = "W" if won(rows[0]) else "L"
    count = 0
    for row in rows:
        if won(row) == (streak_type == "W"):
            count += 1
        else:
            break

    return {
        "streak_type": streak_type,
        "streak_count": count,
        "streak_label": f"{streak_type}{count}",
    }
