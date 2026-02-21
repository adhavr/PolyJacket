"""
FastAPI Backend for Georgia Tech IM Prediction Market
Fetches game data from IMLeagues API endpoint
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import httpx
from bs4 import BeautifulSoup
from typing import List, Optional
from pydantic import BaseModel
import os
import json
from pathlib import Path
from datetime import datetime, timedelta

app = FastAPI(title="GT IM Prediction Market API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For hackathon - be more restrictive in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (frontend)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Cache file for development
CACHE_FILE = Path("games_cache.json")


class Game(BaseModel):
    """Game data model"""
    game_id: str
    home_team: str
    away_team: str
    home_score: str
    away_score: str
    time: str
    date: Optional[str] = None
    sport: str
    status: str
    location: Optional[str] = None
    league: Optional[str] = None
    home_record: Optional[str] = None
    away_record: Optional[str] = None


class GamesResponse(BaseModel):
    """API response model"""
    success: bool
    total_games: int
    games: List[Game]
    message: Optional[str] = None


@app.get("/")
async def root():
    """Serve the frontend"""
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"message": "GT IM Prediction Market API", "docs": "/docs"}


@app.get("/api/games", response_model=GamesResponse)
async def get_games():
    """
    Get games from cache file (for development)
    Use /api/games/refresh to fetch fresh data from API
    """
    
    try:
        # Read from cache file
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r') as f:
                data = json.load(f)
                games = [Game(**game) for game in data.get('games', [])]
                
                print(f"Returning {len(games)} games from cache")
                
                return GamesResponse(
                    success=True,
                    total_games=len(games),
                    games=games,
                    message=f"Loaded {len(games)} games from cache"
                )
        else:
            return GamesResponse(
                success=False,
                total_games=0,
                games=[],
                message="No cached data found. Use /api/games/refresh to fetch from API"
            )
    except Exception as e:
        print(f"Error reading cache: {e}")
        import traceback
        traceback.print_exc()
        return GamesResponse(
            success=False,
            total_games=0,
            games=[],
            message=f"Error reading cache: {str(e)}"
        )


@app.get("/api/games/refresh", response_model=GamesResponse)
async def refresh_games():
    """
    Fetch fresh games from IMLeagues API and save to cache
    
    This endpoint:
    1. Fetches games for each day in our range (last 3 days + next 7 days)
    2. Uses NewViewMode=0 to get only specific dates (more efficient than fetching full month)
    3. Parses the HTML to extract game data with dates and scores
    4. Saves to cache file for future requests
    5. Returns clean JSON with completed game scores
    """
    
    try:
        # Fetch games from API
        games = await fetch_all_games()
        
        # Save to cache file
        cache_data = {
            'games': [game.dict() for game in games],
            'count': len(games),
            'last_updated': str(datetime.now())
        }
        
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        print(f"Fetched and cached {len(games)} games")
        
        return GamesResponse(
            success=True,
            total_games=len(games),
            games=games,
            message=f"Successfully fetched and cached {len(games)} games (last 3 days + next 7 days)"
        )
    except Exception as e:
        print(f"Error fetching games: {e}")
        import traceback
        traceback.print_exc()
        return GamesResponse(
            success=False,
            total_games=0,
            games=[],
            message=f"Error fetching games: {str(e)}"
        )


async def fetch_all_games() -> List[Game]:
    """
    Fetch games for each day in our date range using AjaxSearchGamesForSPAManageGames endpoint
    This is more efficient as it only fetches the exact dates we need (last 3 days + next 7 days)
    
    Returns:
        List of Game objects
    """
    from datetime import datetime, timedelta
    
    # Calculate date range: last 3 days to next 7 days
    today = datetime.now().date()
    start_date = today - timedelta(days=3)
    end_date = today + timedelta(days=7)
    
    all_games = []
    
    # Fetch games for each day in the range
    async with httpx.AsyncClient(timeout=30.0) as client:
        print(f"\n=== Fetching games from {start_date} to {end_date} (day by day) ===")
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%m/%d/%Y").lstrip("0").replace("/0", "/")
            
            # Fetch games for this specific date
            games = await fetch_games_for_specific_date(client, date_str)
            
            if games:
                print(f"  {date_str}: {len(games)} games")
                all_games.extend(games)
            
            current_date += timedelta(days=1)
        
        print(f"Total games fetched: {len(all_games)}")
        return all_games


async def fetch_games_for_specific_date(client: httpx.AsyncClient, date_str: str) -> List[Game]:
    """
    Fetch games for a specific date
    
    Args:
        client: httpx AsyncClient to reuse connection
        date_str: Date string in format M/D/YYYY (e.g., "2/15/2026")
        
    Returns:
        List of Game objects for that date
    """
    url = "https://www.imleagues.com/AjaxPageRequestHandler.aspx"
    
    params = {
        "class": "imLeagues.Web.Members.Pages.BO.School.ManageGamesBO",
        "method": "AjaxSearchGamesForSPAManageGames"
    }
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.imleagues.com",
        "Referer": "https://www.imleagues.com/spa/intramural/13cc30785f6f4658aebbb07d83e19f67/managegames",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    
    # Using NewViewMode=0 returns only the selected date (more efficient!)
    payload = {
        "MemberId": "guest",
        "SchoolId": "13cc30785f6f4658aebbb07d83e19f67",
        "CategoryId": "0",
        "SportId": "",
        "LeagueId": "",
        "DivisionId": "",
        "FacilityId": "",
        "SurfaceId": "",
        "OfficialId": "",
        "CompleteGames": 0,
        "PublishedGames": 0,
        "StartDate": date_str,
        "EndDate": date_str,
        "ViewMode": "0",
        "SelectedDate": date_str,
        "ClubOrNot": "1",
        "RequestType": 1,
        "NewViewMode": 0  # Key: 0 = single date, 2 = full month
    }
    
    try:
        response = await client.post(url, params=params, json=payload, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        
        if not data.get('Data'):
            return []
        
        html_content = data['Data']
        
        # Parse HTML with BeautifulSoup
        games = parse_games_html_with_dates(html_content)
        
        return games
        
    except Exception as e:
        print(f"Error fetching games for {date_str}: {e}")
        return []


async def fetch_games_for_date(date_str: str) -> List[Game]:
    """
    Fetch games for a specific date
    
    Args:
        date_str: Date string in format MM/DD/YYYY
        
    Returns:
        List of Game objects
    """
    # IMLeagues API endpoint
    url = "https://www.imleagues.com/Services/AjaxRequestHandler.ashx"
    
    params = {
        "class": "imLeagues.Web.Members.Services.BO.Network.ManageGamesBO",
        "method": "Initialize",
        "paramType": "imLeagues.Internal.API.VO.Input.Network.ManageGamesViewInVO",
        "urlReferrer": "https://www.imleagues.com/spa/intramural/13cc30785f6f4658aebbb07d83e19f67/managegames"
    }
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://www.imleagues.com",
        "Referer": "https://www.imleagues.com/spa/intramural/13cc30785f6f4658aebbb07d83e19f67/managegames",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    }
    
    payload = {
        "entityId": "13cc30785f6f4658aebbb07d83e19f67",
        "entityType": "intramural",
        "pageType": "Intramural",
        "resultsFilter": 0,
        "clientVersion": "572",
        "isMobileDevice": True,
        "isSSO": False,
        "cachedKey": None,
        "clientType": 0,
        "selectedDate": date_str  # Add the date parameter
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print(f"\n=== Fetching games for date: {date_str} ===")
            print(f"Payload: {payload}")
            
            response = await client.post(url, params=params, json=payload, headers=headers)
            response.raise_for_status()
            
            # Parse JSON response
            data = response.json()
            
            # Extract HTML from the nested structure
            if "data" not in data or "manageGamesUCHtml" not in data["data"]:
                print(f"No games HTML found for {date_str}")
                return []
            
            html_content = data["data"]["manageGamesUCHtml"]
            print(f"HTML length for {date_str}: {len(html_content)} characters")
            
            # Parse HTML with BeautifulSoup
            games = parse_games_html(html_content, date_str)
            print(f"Parsed {len(games)} games for {date_str}")
            
            return games
            
    except Exception as e:
        print(f"Error fetching games for {date_str}: {e}")
        return []


def parse_games_html_with_dates(html_content: str) -> List[Game]:
    """
    Parse the HTML string to extract game information with proper date grouping
    
    Args:
        html_content: HTML string from the API response
        
    Returns:
        List of Game objects with proper dates from gameday attribute
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    games = []
    
    # Find all date sections (divs with gameday attribute)
    date_sections = soup.select('div[gameday]')
    
    print(f"Found {len(date_sections)} date sections")
    
    for date_section in date_sections:
        # Get the date for this section
        current_date = date_section.get('gameday')
        
        # Find all game containers within this date section
        # Use more flexible selector to catch all games
        game_elements = date_section.select('div.match')
        
        print(f"  Date {current_date}: {len(game_elements)} games")
        
        for game_elem in game_elements:
            try:
                # Extract game ID from data-id attribute
                game_id = game_elem.get('data-id', '')
                
                # Try multiple selectors for teams to handle different HTML structures
                # First try the specific structure with iml-team-left/right
                home_team_container = game_elem.select_one('div.iml-team-left')
                home_team_elem = home_team_container.select_one('a.teamHome') if home_team_container else None
                
                # Fallback to direct selector if specific structure not found
                if not home_team_elem:
                    home_team_elem = game_elem.select_one('a.teamHome, .teamHome')
                
                away_team_container = game_elem.select_one('div.iml-team-right')
                away_team_elem = away_team_container.select_one('a.teamAway') if away_team_container else None
                
                # Fallback to direct selector if specific structure not found
                if not away_team_elem:
                    away_team_elem = game_elem.select_one('a.teamAway, .teamAway')
                
                if not home_team_elem or not away_team_elem:
                    continue
                
                home_team = home_team_elem.get_text(strip=True)
                away_team = away_team_elem.get_text(strip=True)
                
                # Extract scores - CRITICAL: Use .get_text() to recursively extract from nested spans
                # The score might be directly in <strong> OR nested in <span class='match-win'>
                home_score_elem = game_elem.select_one('strong.match-team1Score, .match-team1Score')
                away_score_elem = game_elem.select_one('strong.match-team2Score, .match-team2Score')
                
                # Use .get_text(strip=True) to recursively extract text from nested elements
                home_score_text = home_score_elem.get_text(strip=True) if home_score_elem else "--"
                away_score_text = away_score_elem.get_text(strip=True) if away_score_elem else "--"
                
                # Check for forfeit/default indicators
                forfeit_elem = game_elem.select_one('small.text-muted')
                forfeit_text = forfeit_elem.get_text(strip=True).lower() if forfeit_elem else ""
                is_forfeit = 'forfeit' in forfeit_text or 'default' in forfeit_text
                
                # Determine status based on score values and forfeit status
                if home_score_text == "--" and away_score_text == "--":
                    if is_forfeit:
                        status = "forfeit"
                        home_score = "--"
                        away_score = "--"
                    else:
                        status = "scheduled"
                        home_score = "--"
                        away_score = "--"
                elif home_score_text.isdigit() and away_score_text.isdigit():
                    if is_forfeit:
                        status = "forfeit"
                    else:
                        status = "completed"
                    home_score = home_score_text
                    away_score = away_score_text
                else:
                    # Handle partial scores or other edge cases
                    if is_forfeit:
                        status = "forfeit"
                    else:
                        status = "unknown"
                    home_score = home_score_text
                    away_score = away_score_text
                
                # Extract time
                time_elem = game_elem.select_one('.time')
                game_time = time_elem.get_text(strip=True) if time_elem else "TBD"
                
                # Extract sport (from the sport link)
                sport_elem = game_elem.select_one('a[href*="/sport/"]')
                sport = sport_elem.get_text(strip=True) if sport_elem else "Unknown"
                
                # Extract location/venue (facility + court)
                facility_elem = game_elem.select_one('.match-facility')
                court_elem = game_elem.select_one('.iml-game-court')
                
                if facility_elem and court_elem:
                    facility = facility_elem.get_text(strip=True)
                    court = court_elem.get_text(strip=True)
                    location = f"{facility}, {court}"
                elif facility_elem:
                    location = facility_elem.get_text(strip=True)
                else:
                    location = None
                
                # Extract league info
                league_elem = game_elem.select_one('a[href*="/league/"]')
                league = league_elem.get_text(strip=True) if league_elem else None
                
                # Extract team records (W-L-T format)
                # Records are in <small class="text-muted"> within each team's .media container
                home_record = None
                away_record = None
                
                # Find all .media containers within the game (one for home, one for away)
                team_media_containers = game_elem.find_all('div', class_='media')
                
                # The first .media should be home team, second should be away team
                for media in team_media_containers:
                    # Check if this media contains the home team or away team
                    team_link = media.select_one('.teamHome, .teamAway')
                    if not team_link:
                        continue
                    
                    # Find the record in this media's body
                    media_body = media.select_one('.media-body')
                    if media_body:
                        record_elem = media_body.select_one('small.text-muted')
                        if record_elem:
                            record_text = record_elem.get_text(strip=True)
                            # Only capture if it looks like a record (contains digits and hyphens)
                            if '-' in record_text and '(' in record_text:
                                # Determine if this is home or away based on the team class
                                if 'teamHome' in team_link.get('class', []):
                                    home_record = record_text
                                elif 'teamAway' in team_link.get('class', []):
                                    away_record = record_text
                
                game = Game(
                    game_id=game_id,
                    home_team=home_team,
                    away_team=away_team,
                    home_score=home_score,
                    away_score=away_score,
                    time=game_time,
                    date=current_date,
                    sport=sport,
                    status=status,
                    location=location,
                    league=league,
                    home_record=home_record,
                    away_record=away_record
                )
                
                games.append(game)
                
            except Exception as e:
                # Skip games that fail to parse
                print(f"Error parsing game: {e}")
                continue
    
    return games


def parse_games_html(html_content: str, date_str: str = None) -> List[Game]:
    """
    Parse the HTML string to extract game information
    
    Args:
        html_content: HTML string from the API response
        date_str: Date string to use for all games (passed from fetch_games_for_date)
        
    Returns:
        List of Game objects
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    games = []
    
    # Use the date_str parameter that was passed in, which corresponds to the date we requested
    # Don't extract from HTML as it may not reflect the selectedDate parameter
    current_date = date_str
    
    # Only fall back to HTML if date_str wasn't provided
    if not current_date:
        date_elem = soup.select_one('#pNowDate')
        current_date = date_elem.get_text(strip=True) if date_elem else None
    
    if not current_date:
        game_day_elem = soup.select_one('[gameday]')
        if game_day_elem:
            current_date = game_day_elem.get('gameday')
    
    # Find all game containers (divs with class 'match')
    game_elements = soup.select('div.match')
    
    for game_elem in game_elements:
        try:
            # Extract game ID
            game_id = game_elem.get('data-id', '')
            
            # Extract teams
            home_team_elem = game_elem.select_one('.teamHome')
            away_team_elem = game_elem.select_one('.teamAway')
            
            if not home_team_elem or not away_team_elem:
                continue
            
            home_team = home_team_elem.get_text(strip=True)
            away_team = away_team_elem.get_text(strip=True)
            
            # Extract scores
            home_score_elem = game_elem.select_one('.match-team1Score')
            away_score_elem = game_elem.select_one('.match-team2Score')
            
            home_score = home_score_elem.get_text(strip=True) if home_score_elem else "--"
            away_score = away_score_elem.get_text(strip=True) if away_score_elem else "--"
            
            # Extract time
            time_elem = game_elem.select_one('.time')
            game_time = time_elem.get_text(strip=True) if time_elem else "TBD"
            
            # Extract sport (from the sport link)
            sport_elem = game_elem.select_one('a[href*="/sport/"]')
            sport = sport_elem.get_text(strip=True) if sport_elem else "Unknown"
            
            # Extract location/venue
            location_elem = game_elem.select_one('.location, .venue')
            location = location_elem.get_text(strip=True) if location_elem else None
            
            # Extract league info
            league_elem = game_elem.select_one('a[href*="/league/"]')
            league = league_elem.get_text(strip=True) if league_elem else None
            
            # Determine status
            if home_score == "--" or away_score == "--":
                status = "scheduled"
            elif home_score.isdigit() and away_score.isdigit():
                # Check if game is complete or in progress
                # For now, assume any game with scores is complete
                # You could add more logic here based on additional fields
                status = "completed"
            else:
                status = "unknown"
            
            game = Game(
                game_id=game_id,
                home_team=home_team,
                away_team=away_team,
                home_score=home_score,
                away_score=away_score,
                time=game_time,
                date=current_date,
                sport=sport,
                status=status,
                location=location,
                league=league
            )
            
            games.append(game)
            
        except Exception as e:
            # Skip games that fail to parse
            print(f"Error parsing game: {e}")
            continue
    
    return games


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "GT IM Prediction Market API"}


if __name__ == "__main__":
    import uvicorn
    # Set reload=False for stability during testing
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
