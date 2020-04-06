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
        self.run_simulation()
        self.results=[]


    def model(self,t):
        S, E, I, A, R = [self.S_0/self.N], [self.E_0/self.N], [self.I_0/self.N], [self.A_0/self.N], [self.R_0/self.N]

        dt = t[1] - t[0]
        for _ in t[1:]:
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
        self.asymptomatic_infected = []
        self.df = pd.DataFrame()
        self.df_from_loop = pd.DataFrame()
        self.df_predict = pd.DataFrame()
        self.R0D = int

        self.loop_countries(p)

    @staticmethod
    def next_gen(r0, tau, c0, ct):
        r0d = r0 / tau
        # return ct * (1 + r0d) ** tau - c0 * r0d * (1 + r0d) ** (tau - 1)
        return (1 + r0d) * (ct - c0) # (1+3.082/14) * (5825-846)

    @staticmethod
    def true_a(fi, theta, d, d_prev):
        delta_detected = (d - d_prev)
        prev_asymptomatic_infected = 1 / (1 - fi) * (delta_detected / theta + d_prev)
        return prev_asymptomatic_infected

    def loop_countries(self, p):

        for country in p.country:
            self.df = p.df[p.df['country'] == country]
            self.increasing_values(p.init_infected)
            self.calc_r(tau=p.tau)
            self.predict(tau=p.tau, scenario=p.scenario)
            self.calc_asymptomatic(fi=p.fi, theta=p.theta, init_infected=p.init_infected)
            self.write(tau=p.tau)

            self.df_predict = pd.concat([self.df_predict, self.write(tau=p.tau)])
            self.df_from_loop = pd.concat([self.df, self.df_from_loop])


    def increasing_values(self, init_infected):
        detected = self.df['I'].values
        day_0 = np.argmax(detected > init_infected)
        detected = detected[day_0 - 1:]

        self.detected = []
        for t in range(1, len(detected)):
            self.detected.append(max(detected[t - 1], detected[t]))

        print(len(self.df), len(self.detected))
        self.df = self.df[day_0:]
        print(len(self.df))
        self.df.loc[:, 'I'] = self.detected

    def calc_r(self, tau):
        detected = self.detected
        r_values = np.array([])

        for t in range(1, len(detected)):
            if t <= tau:
                r_value = (detected[t] / (detected[t - 1] + 1e-05) - 1) * tau
            else:
                r_value = (detected[t] / (detected[t - 1] - detected[t - tau] + detected[t - tau - 1]) - 1) * tau
            r_values = np.append(r_values, r_value)

        rma = np.convolve(r_values, np.ones((tau,)) / tau, mode='full')[:-tau + 1]
        self.R0D = rma[-1]

    def predict(self, tau, scenario):
        detected = self.detected

        t = len(detected) - 1   # (1+3.082/14) * (5825-846)
        cnt = 0
        for i in scenario['t'].keys():

            while cnt <= scenario['t'].get(i):
                c0 = detected[t - tau] if len(detected) - tau >= 0 else 0
                next_gen = self.next_gen(r0=self.R0D * scenario['R0D'].get(i) / 100, tau=tau, c0=c0, ct=detected[t])
                detected.append(next_gen)
                print(cnt, t, t - tau, c0, np.round(detected[t], 1), np.round(next_gen, 1))
                t += 1
                cnt += 1


    def calc_asymptomatic(self, fi, theta, init_infected):

        asymptomatic_infected = [self.true_a(fi=fi, theta=theta, d=self.detected[0], d_prev=init_infected)]

        for t in range(1, len(self.detected)):
            prev_asymptomatic_infected = self.true_a(fi=fi, theta=theta, d=self.detected[t], d_prev=self.detected[t - 1])
            # print('{0:.0f}, {1:.0f}, {2:.0f}, {3:.0f}, {4:.0f}, {5:.0f}'.format(t,
            #                                                                     self.detected[t - 1],
            #                                                                     self.detected[t],
            #                                                                     asymptomatic_infected[-1],
            #                                                                     prev_asymptomatic_infected,
            #                                                                     max(asymptomatic_infected[-1],
            #                                                                         prev_asymptomatic_infected)))
            asymptomatic_infected.append(prev_asymptomatic_infected)
            # asymptomatic_infected.append(max(asymptomatic_infected[-1], prev_asymptomatic_infected))

        self.asymptomatic_infected = asymptomatic_infected

    def write(self, tau):

        asymptomatic =np.array(self.asymptomatic_infected- np.array(self.detected))
        asymptomatic[0] = 0
        predict_date = self.df['date'].max() +  pd.to_timedelta(1, unit="D")
        periods = len(self.detected) - len(self.df)
        predict_dates = pd.date_range(start=predict_date.strftime('%Y-%m-%d'), periods=periods)

        self.df['A'] = asymptomatic[:-periods]
        self.df['E'] = self.asymptomatic_infected[:-periods]

        df_predict = pd.DataFrame({'date': predict_dates, 'I': self.detected[-periods:]})
        df_predict['A'] = asymptomatic[-periods:]
        df_predict['E'] = None
        df_predict.iloc[:-tau, 3] = self.asymptomatic_infected[-(periods-tau):]
        df_predict['country'] = self.df['country'].head(1).values[0]
        return df_predict


class CountryData:
    def __init__(self, country_file):
        self.filepath = country_file
        self.df = self.build_country_data()

    def build_country_data(self):
        country_df = pd.read_csv(self.filepath)
        # country_df = country_df.set_index('Country')
        country_df = country_df.drop(columns="Unnamed: 0")
        # country_df['date'] = country_df['date'].apply(lambda x: x if x.month<4 else x - relativedelta(years=1))
        country_df['date'] = pd.to_datetime(country_df['date'],format="%d/%m/%Y")
        return country_df
