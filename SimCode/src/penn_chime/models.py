"""Models.

Changes affecting results or their presentation should also update
parameters.py `change_date`, so users can see when results have last
changed
"""

from __future__ import annotations

from typing import Dict, Generator, Tuple

import numpy as np  # type: ignore
import pandas as pd  # type: ignore

from .parameters import Parameters

from seirsplus.models import *
import networkx

class SimSirModel:

    def __init__(self, p: Parameters) -> SimSirModel:
        # TODO missing initial recovered value
        susceptible = p.susceptible
        recovered = 0.0
        recovery_days = p.recovery_days

        rates = {
            key: d.rate
            for key, d in p.dispositions.items()
        }

        lengths_of_stay = {
            key: d.length_of_stay
            for key, d in p.dispositions.items()
        }

        # Note: this should not be an integer.
        # We're appoximating infected from what we do know.
        # TODO market_share > 0, hosp_rate > 0
        infected = (
            p.current_hospitalized / p.market_share / p.hospitalized.rate
        )

        detection_probability = (
            p.known_infected / infected if infected > 1.0e-7 else None
        )

        intrinsic_growth_rate = \
            (2.0 ** (1.0 / p.doubling_time) - 1.0) if p.doubling_time > 0.0 else 0.0

        gamma = 1.0 / recovery_days

        # Contact rate, beta
        beta = (
            (intrinsic_growth_rate + gamma)
            / susceptible
            * (1.0 - p.relative_contact_rate)
        )  # {rate based on doubling time} / {initial susceptible}

        # r_t is r_0 after distancing
        r_t = beta / gamma * susceptible

        # Simplify equation to avoid division by zero:
        # self.r_naught = r_t / (1.0 - relative_contact_rate)
        r_naught = (intrinsic_growth_rate + gamma) / gamma
        doubling_time_t = 1.0 / np.log2(
            beta * p.susceptible - gamma + 1)

        raw_df = sim_sir_df(
            p.susceptible,
            infected,
            recovered,
            beta,
            gamma,
            p.n_days,
        )
        dispositions_df = build_dispositions_df(raw_df, rates, p.market_share)
        admits_df = build_admits_df(dispositions_df)
        census_df = build_census_df(admits_df, lengths_of_stay)

        self.susceptible = susceptible
        self.infected = infected
        self.recovered = recovered

        self.detection_probability = detection_probability
        self.recovered = recovered
        self.intrinsic_growth_rate = intrinsic_growth_rate
        self.gamma = gamma
        self.beta = beta
        self.r_t = r_t
        self.r_naught = r_naught
        self.doubling_time_t = doubling_time_t
        self.raw_df = raw_df
        self.dispositions_df = dispositions_df
        self.admits_df = admits_df
        self.census_df = census_df


def sir(
    s: float, i: float, r: float, beta: float, gamma: float, n: float
) -> Tuple[float, float, float]:
    """The SIR model, one time step."""
    s_n = (-beta * s * i) + s
    i_n = (beta * s * i - gamma * i) + i
    r_n = gamma * i + r
    if s_n < 0.0:
        s_n = 0.0
    if i_n < 0.0:
        i_n = 0.0
    if r_n < 0.0:
        r_n = 0.0

    scale = n / (s_n + i_n + r_n)
    return s_n * scale, i_n * scale, r_n * scale


def gen_sir(
    s: float, i: float, r: float, beta: float, gamma: float, n_days: int
) -> Generator[Tuple[float, float, float], None, None]:
    """Simulate SIR model forward in time yielding tuples."""
    s, i, r = (float(v) for v in (s, i, r))
    n = s + i + r
    for d in range(n_days + 1):
        yield d, s, i, r
        s, i, r = sir(s, i, r, beta, gamma, n)


def sim_sir_df(
    s: float, i: float, r: float, beta: float, gamma: float, n_days: int
) -> pd.DataFrame:
    """Simulate the SIR model forward in time."""
    return pd.DataFrame(
        data=gen_sir(s, i, r, beta, gamma, n_days),
        columns=("day", "susceptible", "infected", "recovered"),
    )

def build_dispositions_df(
    sim_sir_df: pd.DataFrame,
    rates: Dict[str, float],
    market_share: float,
) -> pd.DataFrame:
    """Get dispositions of patients adjusted by rate and market_share."""
    patients = sim_sir_df.infected + sim_sir_df.recovered
    return pd.DataFrame({
        "day": sim_sir_df.day,
        **{
            key: patients * rate * market_share
            for key, rate in rates.items()
        }
    })


def build_admits_df(dispositions_df: pd.DataFrame) -> pd.DataFrame:
    """Build admits dataframe from dispositions."""
    admits_df = dispositions_df.iloc[:-1, :] - dispositions_df.shift(1)
    admits_df.day = dispositions_df.day
    return admits_df


def build_census_df(
    admits_df: pd.DataFrame,
    lengths_of_stay: Dict[str, int],
) -> pd.DataFrame:
    """ALOS for each disposition of COVID-19 case (total guesses)"""
    return pd.DataFrame({
        'day': admits_df.day,
        **{
            key: (
                admits_df[key].cumsum().iloc[:-los]
                - admits_df[key].cumsum().shift(los).fillna(0)
            ).apply(np.ceil)
            for key, los in lengths_of_stay.items()
        }
    })

class Seiar:
    def __init__(self, p: Parameters):

        self.N = p.N
        self.S_0 = p.S_0
        self.E_0 = p.E_0
        self.I_0 = p.I_0
        self.A_0 = p.A_0
        self.R_0 = p.R_0
        self.alpha = p.alpha
        self.beta_ill = p.beta_ill
        self.beta_asy = p.beta_asy
        self.gamma_ill = p.gamma_ill
        self.gamma_asy = p.gamma_asy
        self.rho = p.rho
        self.theta = p.theta
        self.start_date_simulation = p.start_date_simulation
        self.number_of_days = p.number_of_days
        self.projection = p.model_checkpoints
        self.run_simulation()
        self.results=[]


    def model(self,t):
        S, E, I, A, R = [self.S_0/self.N], [self.E_0/self.N], [self.I_0/self.N], [self.A_0/self.N], [self.R_0/self.N]

        dt = t[1] - t[0]
        time_asy, time_ill, beta_asy, beta_ill = self.projection['time_asy'], self.projection['time_ill'], self.projection['beta_asy'], self.projection['beta_ill']
        for tm in t[1:]:
            if tm in time_asy:
                print(tm, beta_asy)
                self.beta_asy = beta_asy[time_asy.index(tm)]
                print(tm, self.beta_asy)
                time_asy.pop(0)
                beta_asy.pop(0)
            if tm in time_ill:
                self.beta_ill = beta_ill[time_ill.index (tm)]
                print(tm, self.beta_ill)
                beta_ill.pop(0)
                time_ill.pop(0)
            next_S = S[-1] - (self.rho * self.beta_ill * S[-1] * I[-1] + self.rho * self.beta_asy * S[-1] * A[-1]) * dt
            next_E = E[-1] + (self.rho * self.beta_ill * S[-1] * I[-1] + self.rho * self.beta_asy * S[-1] * A[-1] - self.alpha * E[-1]) * dt
            next_I = I[-1] + (self.theta * self.alpha * E[-1] - self.gamma_ill * I[-1]) * dt
            next_A = A[-1] + ((1 - self.theta) * self.alpha * E[-1] - self.gamma_asy * A[-1]) * dt
            next_R = R[-1] + (self.gamma_ill * I[-1] + self.gamma_asy * A[-1]) * dt

            S.append(next_S)
            E.append(next_E)
            I.append(next_I)
            A.append(next_A)
            R.append(next_R)

        return np.stack([S, E, I, A, R]).T


    def run_simulation(self):
        t_max = 600
        dt = .01
        t = np.linspace(0, t_max, int(t_max / dt) + 1)

        results = self.model(t)

        df = pd.DataFrame(results)
        df = df.rename(columns={df.columns[0]: 'S', df.columns[1]: 'E', df.columns[2]: 'I', df.columns[3]: 'A', df.columns[4]: 'R'})
        dates = pd.date_range(start=self.start_date_simulation, end='05/01/2030')
        df_I_E = df[::100].reset_index(drop=True)
        df_I_E.index = dates[:len(df_I_E)]

        df_I_E = df_I_E.rename(columns={'S': 'Susceptible', 'E': 'Exposed', 'I': 'Infected', 'A': 'Asymptomatic', 'R': 'Recovered'})
        infected_df = df_I_E[['Infected']] * self.N
        asymptomatic_df = df_I_E[['Asymptomatic']] * self.N
        recovered_df = df_I_E[['Recovered']] * self.N
        susceptible_df = df_I_E[['Susceptible']] * self.N
        exposed_df = df_I_E[['Exposed']] * self.N

        results = [
                    infected_df.loc[:self.number_of_days],
                    asymptomatic_df.loc[:self.number_of_days],
                    recovered_df.loc[:self.number_of_days],
                    susceptible_df.loc[:self.number_of_days],
                    exposed_df.loc[:self.number_of_days]
                   ]

        self.results = pd.concat(results, axis = 1)
        return 0

class OLG:
    """
    calc_asymptomatic start from first case
    exposed are the asymptomatic_infected with lag not only infected
    asymptomatic_infected eq 10 does not always grow but uses two diferent R0

    fi  # proportion of infectives are never diagnosed
    theta = theta  # diagnosis daily rate





    """
    def __init__(self, p: Parameters):

        self.detected = []
        self.increasing_values(p.detected, p.init_infected)

        self.RMA, self.R0D = self.calc_r(tau=p.tau)

        self.detected = self.predict(tau=p.tau)


        self.asymptomatic_infected = self.calc_asymptomatic(fi=p.fi, theta=p.theta)
        self.df = self.write(tau=p.tau)


    @staticmethod
    def calc_next_gen(r0=4.9636, tau=14, C_t=70, C_o=0):
        return C_t * (1 + r0 / tau) ** tau - C_o * r0 / tau * (1 + r0 / tau) ** (tau - 1)


    def increasing_values(self, detected, init_infected):
        day_0 = np.argmax(detected > init_infected)
        detected = detected[day_0-1:]

        for t in range(1, len(detected)):
            self.detected.append(max(detected[t - 1], detected[t]))


    def calc_r(self, tau):
        detected = self.detected

        r_values = np.array([])

        for t in range(1, tau + 1):
            r_value = (detected[t] /(detected[t - 1]  + 1e-05) - 1) * tau
            r_values = np.append(r_values, r_value)


        for t in range(tau + 1, len(detected)):
            r_value = (detected[t] / (detected[t - 1] -detected[t - tau] +detected[t - tau - 1]) - 1) * tau
            r_values = np.append(r_values, r_value)


        rma = np.convolve(r_values, np.ones((tau,)) / tau, mode='full')

        return rma, rma[-1]




    def calc_asymptomatic(self, fi, theta):

        asymptomatic_infected = np.array([self.detected[0]])

        for t in range(1, len(self.detected)):
            cur_asymptomatic_infected = 1 / (1 - fi) * (self.detected[t] / theta)
            asymptomatic_infected = np.append(asymptomatic_infected,  cur_asymptomatic_infected)

        return asymptomatic_infected

    def predict(self, tau):
        detected = self.detected

        for i in range(len(detected) - tau, len(detected)):
            detected = np.append(detected, self.calc_next_gen(r0=self.R0D, tau=tau, C_t=detected[i], C_o=detected[i-tau]))
        return detected


    def write(self, tau):
        periods  = len(self.detected)

        asymptomatic = self.asymptomatic_infected - self.detected
        exposed = self.asymptomatic_infected

        df = pd.DataFrame({'asymptomatic': asymptomatic,
                           'infected': self.detected,
                           'exposed': exposed
                           })

        df['dates'] = pd.date_range(end=pd.to_datetime('today').strftime('%Y-%m-%d'), periods=periods)
        df['asymptomatic'].clip(lower=0, inplace=True)
        df['exposed'] = df['exposed'].shift(-tau)

        return df


class CountryData:
    def __init__(self, country_file, stringency_file, sir_file):
        self.country_file = country_file
        self.sir_file = sir_file
        self.stringency_file = stringency_file
        self.country_df = self.get_country_data()
        self.stringency_df = self.get_country_stringency()
        self.df = self.get_data()
        self.sir_df = self.get_sir()

    def get_country_data(self):
        country_df = pd.read_csv(self.country_file)
        # country_df = country_df.set_index('Country')
        country_df = country_df.drop(columns="Unnamed: 0")
        # country_df['date'] = country_df['date'].apply(lambda x: x if x.month<4 else x - relativedelta(years=1))
        country_df['date'] = pd.to_datetime(country_df['date'],format="%d/%m/%Y")
        # country_df['date'] = pd.to_datetime(country_df['date'], format="%Y-%m-%d")

        return country_df

    def get_country_stringency(self):
        country_st_df = pd.read_excel(self.stringency_file)
        country_st_df['date'] = pd.to_datetime(country_st_df['Date'], format="%Y%m%d")
        return country_st_df

    def get_data(self):
        df = self.country_df.merge(self.stringency_df, left_on=["Country", "date"], right_on=["CountryName", "date"])
        return df

    def get_sir(self):
        sir_df = pd.read_csv(self.sir_file)
        # sir_df = sir_df.set_index('Country')
        sir_df = sir_df.drop(columns="Unnamed: 0")
        # sir_df['date'] = sir_df['date'].apply(lambda x: x if x.month<4 else x - relativedelta(years=1))
        # sir_df['date'] = pd.to_datetime(sir_df['date'],format="%d/%m/%Y")
        sir_df['date'] = pd.to_datetime(sir_df['date'], format="%Y-%m-%d")
        sir_df['country'] = sir_df['country'].str.capitalize()
        sir_df = sir_df.rename(columns={'country':'Country'})
        return sir_df

class IsraelData:
    def __init__(self, israel_file):
        self.filepath = israel_file
        self.df = self.get_data()

    def get_data(self):
        df = pd.read_excel(self.filepath)
        colnames = df.columns
        df = df.melt(id_vars=['יישוב'], value_vars=colnames[1:])
        df['variable'] = pd.to_datetime(df['variable'],format="%d/%m/%Y", errors='coerce')
        df = df[df["variable"].dt.year>1677].dropna()
        df = df.rename(columns={'יישוב':'Yishuv', 'variable':'date'})
        return df