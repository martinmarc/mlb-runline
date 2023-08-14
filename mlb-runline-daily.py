# -*- coding: utf-8 -*-
"""
Created 2023

@author: Quant Galore
"""

from datetime import datetime, timedelta

import pandas as pd
import statsapi
import requests
import numpy as np
import sqlalchemy
from constants import API_KEY, database_name, sql_hostname
import mysql.connector
from helper_functions import name_converter


# =============================================================================
# Start 
# =============================================================================

# This is the production dataset, designed to only append new values, as oppposed to having to constantly re-build the dataset
# So, we set the start date to 7 days prior. This way, we check all of the games in that period to include any days that we missed

begin_date = (datetime.today()).strftime("%Y-%m-%d")
ending_date = (datetime.today()).strftime("%Y-%m-%d")

Schedule = statsapi.schedule(start_date = begin_date, end_date = ending_date)
Schedule_DataFrame = pd.json_normalize(Schedule)

date_range = pd.date_range(start = begin_date, end = ending_date)

odds_list = []

# The spread market represents the "runline" bet

market = "spread"

for date in date_range:

    date = date.strftime("%Y-%m-%d")
    url = f"https://api.prop-odds.com/beta/games/mlb?date={date}&tz=America/Chicago&api_key={API_KEY}"
    games_url = f"https://api.prop-odds.com/beta/games/mlb?date={date}&api_key={API_KEY}"
    
    
    games = pd.json_normalize(requests.get(games_url).json()["games"])
    
    if len(games) < 1:
        
        continue
    
    for game_id in games["game_id"]:
        
        Game = games[games["game_id"] == game_id]
        
        sportsbook = []
    
        odds_url = f"https://api.prop-odds.com/beta/odds/{game_id}/{market}?api_key={API_KEY}"
        odds = requests.get(odds_url).json()
        
        if len(odds) < 2:
            continue
        
        else:
            
            # DraftKings generally offers the best odds, so for uniformity, we only include odds sourced from DraftKings
            
            for book in odds["sportsbooks"]:
                
                if book["bookie_key"] == "draftkings":
                    sportsbook = book
                else:
                    continue
                
            if len(sportsbook) < 1:
                
                continue
                
            odds_data = pd.json_normalize(sportsbook["market"]["outcomes"])
            
            # The runline (-1.5) refers to the favorite winning by 2 or more points, so we have to first pull who the favorite is
            
            moneyline_url = f"https://api.prop-odds.com/beta/odds/{game_id}/moneyline?api_key={API_KEY}"
            moneyline_odds = requests.get(moneyline_url).json()
            
            if len(moneyline_odds) < 2:
                continue
            
            else:
                
                for moneyline_book in moneyline_odds["sportsbooks"]:
                    
                    if moneyline_book["bookie_key"] == "draftkings":
                        moneyline_sportsbook = moneyline_book
                    else:
                        continue
                    
                if len(moneyline_sportsbook) < 1:
                    
                    continue
            
            moneyline_odds_data = pd.json_normalize(moneyline_sportsbook["market"]["outcomes"])
            
            if moneyline_odds_data["odds"].max() < 0:
                continue
            
            moneyline_favorite = moneyline_odds_data[moneyline_odds_data["odds"] < 0].sort_values(by = "timestamp", ascending = True).head(1)["name"].iloc[0]
            moneyline_underdog = moneyline_odds_data[moneyline_odds_data["odds"] > 0].sort_values(by = "timestamp", ascending = True).head(1)["name"].iloc[0]
            
            # We sort by earliest available pre-game odds first, since the API may occasionally include odds that were set mid-game.
            
            favorite = odds_data[(odds_data["handicap"] == -1.5) & (odds_data["name"] == moneyline_favorite)].sort_values(by = "timestamp", ascending = True).head(1)
            underdog = odds_data[(odds_data["handicap"] == 1.5) & (odds_data["name"] == moneyline_underdog)].sort_values(by = "timestamp", ascending = True).head(1)
            
            if len(favorite) < 1:
                continue
            elif len(underdog) < 1:
                continue
            
            team_1_favorite = favorite["name"].drop_duplicates().iloc[0]
            team_2_underdog = underdog["name"].drop_duplicates().iloc[0]
            
            team_1_favorite_odds = favorite["odds"].iloc[0]
            team_2_underdog_odds = underdog["odds"].iloc[0]
            
            odds_dataframe = pd.DataFrame([[team_1_favorite, team_1_favorite_odds, team_2_underdog, team_2_underdog_odds]],
                                          columns = ["team_1", "team_1_spread_odds", "team_2", "team_2_spread_odds"])
                
            full_odds_dataframe = pd.concat([Game.reset_index(drop = True), odds_dataframe], axis = 1)
            
            if len(full_odds_dataframe) > 1:
                continue
            
            odds_list.append(full_odds_dataframe)
            
full_odds = pd.concat(odds_list).reset_index(drop = True).rename(columns = {"away_team":"away_name",
                                                                            "home_team":"home_name",
                                                                            "start_timestamp":"game_datetime"})

Merged_DataFrame = pd.merge(Schedule_DataFrame, full_odds, on = ["game_datetime", "away_name", "home_name"])

Merged_DataFrame["team_1"] = Merged_DataFrame["team_1"].apply(name_converter)
Merged_DataFrame["team_2"] = Merged_DataFrame["team_2"].apply(name_converter)

Featured_Merged_DataFrame = Merged_DataFrame[["game_datetime","away_name","home_name", "team_1", "team_1_spread_odds", "team_2", "team_2_spread_odds", "venue_name"]].copy().set_index("game_datetime")

# "team_1" always represents the favorite

Featured_Spread_DataFrame = Featured_Merged_DataFrame[["team_1", "team_1_spread_odds", "team_2", "team_2_spread_odds", "venue_name"]].copy().reset_index().set_index("game_datetime")

# To weed out any errors in the data set, we ensure to only include data where the odds are between -200 to +200
# The odds for these bets are almost never set outside of that range, so we exclude them.

Featured_Spread_DataFrame = Featured_Spread_DataFrame[(abs(Featured_Spread_DataFrame["team_1_spread_odds"]) < 200) & (abs(Featured_Spread_DataFrame["team_2_spread_odds"]) < 200)]
Featured_Spread_DataFrame = Featured_Spread_DataFrame[Featured_Spread_DataFrame["team_1"] != Featured_Spread_DataFrame["team_2"]]
#Featured_Spread_DataFrame.index = pd.to_datetime(Featured_Spread_DataFrame.index).tz_convert("America/Chicago")
Featured_Spread_DataFrame.index = pd.to_datetime(Featured_Spread_DataFrame.index).tz_localize(tz=None)

# =============================================================================
# End
# =============================================================================

# We initialize our sqlalchemy engine, then submit the data to the database

engine = sqlalchemy.create_engine(f'{sql_hostname}/{database_name}')

# The daily production dataset should be dropped each day, sa

with engine.connect() as conn:
    result = conn.execute(sqlalchemy.text('DROP TABLE IF EXISTS baseball_spread_production'))

Featured_Spread_DataFrame.to_sql("baseball_spread_production", con = engine, if_exists = "append")
