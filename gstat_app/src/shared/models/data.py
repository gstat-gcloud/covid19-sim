import pandas as pd
import streamlit as st


class CountryData:
    def __init__(self, country_files):
        self.country_files = country_files
        self.country_df = self.get_country_data()
        self.stringency_df = self.get_country_stringency()
        self.df = self.get_data()
        self.sir_df = self.get_sir()
        self.jh_confirmed_df = self.get_jhopkins_confirmed()

    def get_country_data(self):
        country_df = pd.read_csv(self.country_files['country_file'])
        # country_df = country_df.set_index('Country')
        country_df = country_df.drop(columns="Unnamed: 0")
        # country_df['date'] = country_df['date'].apply(lambda x: x if x.month<4 else x - relativedelta(years=1))
        # country_df['date'] = pd.to_datetime(country_df['date'],format="%d/%m/%Y")
        country_df['date'] = pd.to_datetime(country_df['date'], format="%Y-%m-%d")
        # country_df = country_df.rename(columns={'country': 'Country'})
        country_df['Country'] = country_df['country']
        # country_df['new_deaths'] = country_df['new_deaths'].str.replace('+', '')
        # country_df['new_deaths'] = country_df['new_deaths'].str.replace(',', '')
        # country_df['new_deaths'] = country_df['new_deaths'].apply(lambda x: float(x))
        return country_df

    def get_country_stringency(self):
        country_st_df = pd.read_excel(self.country_files['stringency_file'])
        country_st_df['date'] = pd.to_datetime(country_st_df['Date'], format="%Y%m%d")
        return country_st_df

    def get_data(self):
        df = self.country_df.merge(self.stringency_df, left_on=["Country", "date"], right_on=["CountryName", "date"])
        return df

    def get_sir(self):
        sir_df = pd.read_csv(self.country_files['sir_file'])
        # sir_df = sir_df.set_index('Country')
        sir_df = sir_df.drop(columns="Unnamed: 0")
        # sir_df['date'] = sir_df['date'].apply(lambda x: x if x.month<4 else x - relativedelta(years=1))
        # sir_df['date'] = pd.to_datetime(sir_df['date'],format="%d/%m/%Y")
        sir_df['date'] = pd.to_datetime(sir_df['date'], format="%Y-%m-%d")
        sir_df['country'] = sir_df['country'].str.capitalize()
        sir_df = sir_df.rename(columns={'country': 'Country'})
        return sir_df

    def get_jhopkins_confirmed(self):
        df = pd.read_csv(self.country_files['jhopkins_confirmed'])
        # df = df.drop(columns="Unnamed: 0")
        colnames = df.columns
        df = df.melt(id_vars=['Province/State', 'Country/Region'], value_vars=colnames[2:])
        df['variable'] = pd.to_datetime(df['variable'], format="%m/%d/%y", errors='coerce')
        df = df[df["variable"].dt.year > 1677].dropna(subset=['value'])
        df = df.rename(columns={'Country/Region': 'Country', 'Province/State': 'Province'})
        df['Province'] = df['Province'].fillna('All')
        # df = df.rename(columns={'יישוב':'Yishuv', 'variable':'date'})
        return df


class IsraelData:
    def __init__(self, israel_files):
        self.filepath = israel_files
        self.yishuv_df = self.get_yishuv_data()
        self.isolation_df = self.get_isolation_df()
        self.lab_results_df = self.get_lab_results_df()
        self.tested_df = self.get_tested_df()
        self.patients_df = self.get_patients_df()

    @st.cache
    def get_yishuv_data(self):
        df = pd.read_csv(self.filepath['yishuv_file'])
        df = df.drop(columns="Unnamed: 0")
        id_vars = ['יישוב', 'סוג מידע', 'אוכלוסייה נכון ל- 2018']
        colnames = [c for c in df.columns if c not in id_vars]
        df = df.melt(id_vars=id_vars, value_vars=colnames)
        df.loc[:, 'variable'] = pd.to_datetime(df['variable'], format="%d/%m/%Y", errors='coerce')
        df = df[df["variable"].dt.year > 1677].dropna()
        df = df.rename(columns={'יישוב': 'Yishuv', 'אוכלוסייה נכון ל- 2018': 'pop2018', 'variable': 'date'})
        df.loc[:, 'StringencyIndex'] = 1.
        return df

    @st.cache
    def get_isolation_df(self):
        df = pd.read_csv(self.filepath['isolations_file'])
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index("date", drop=False)
        df = df.drop(columns="_id")
        return df

    @st.cache
    def get_lab_results_df(self):
        df = pd.read_csv(self.filepath['lab_results_file'])
        df['result_date'] = pd.to_datetime(df['result_date'])
        return df

    @st.cache
    def get_tested_df(self):
        df = pd.read_csv(self.filepath['tested_file'])
        df['None'] = df[df.columns[2:]].sum(axis=1)
        df['None'] = df['None'].apply(lambda x: 0 if x > 0 else 1)
        df['At Least One'] = df['None'].apply(lambda x: 0 if x > 0 else 1)
        df['test_date'] = pd.to_datetime(df['test_date'])
        df = df.drop(columns="_id")
        return df

    @st.cache
    def get_patients_df(self):
        df = pd.read_csv(self.filepath['patients_file'])
        df = df.dropna(subset=['New Patients Amount'])
        df.loc[:, 'Date'] = pd.to_datetime(df['Date'], format="%d/%m/%Y")
        # df = df.drop(columns="_id")
        return df