import pandas as pd
import numpy as np

def name_converter(short_name):
    Short_Long_Names = pd.read_csv("short_long_mlb_names.csv")

    long_name = Short_Long_Names[Short_Long_Names["short_name"] == short_name]["long_name"]

    if len(long_name) < 1 :

        return np.nan
    else:

        return long_name.iloc[0]

