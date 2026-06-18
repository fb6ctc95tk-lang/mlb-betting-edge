def get_team_last_10_form(conn, team_id: int, before_date):
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
        LIMIT 10
        """,
        (team_id, team_id, before_date),
    )
    rows = cur.fetchall()
    cur.close()

    wins = 0
    losses = 0
    run_diff = 0

    for home_team_id, away_team_id, home_score, away_score in rows:
        if home_team_id == team_id:
            run_diff += home_score - away_score
            if home_score > away_score:
                wins += 1
            else:
                losses += 1
        else:
            run_diff += away_score - home_score
            if away_score > home_score:
                wins += 1
            else:
                losses += 1

    count = len(rows)
    return {
        "last_10_games_count": count,
        "last_10_wins": wins,
        "last_10_losses": losses,
        "last_10_record": f"{wins}-{losses}",
        "last_10_run_diff": run_diff,
    }
