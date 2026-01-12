# Placeholder recommendation logic
# Later we’ll integrate TMDb + Reddit

def recommend_shows(liked_shows: list[str]) -> list[str]:
    # Dummy logic for now
    if "Breaking Bad" in liked_shows:
        return ["Better Call Saul", "Narcos", "Ozark"]
    if "Stranger Things" in liked_shows:
        return ["Dark", "The OA", "Locke & Key"]
    return ["Succession", "The Boys", "Westworld"]
