def american_odds_to_implied_probability(odds):
    if odds < 0:
        probability = abs(odds) / (abs(odds) + 100)
    else:
        probability = 100 / (odds + 100)

    return round(probability * 100, 2)
