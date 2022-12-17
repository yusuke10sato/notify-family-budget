import glob
import os
import shutil
import time
import traceback
import urllib

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait

dotenv_path = './settings/.env'
load_dotenv(dotenv_path)


def login(browser, LOGIN_URL, USER_ID, PASS):
    browser.get(LOGIN_URL)
    browser.save_screenshot("captures/login-screen.png")
    # ID自動入力
    e = browser.find_element(By.ID, "u")
    e.clear()
    e.send_keys(USER_ID)
    # PASSWORD自動入力
    e = browser.find_element(By.ID, "p")
    e.clear()
    e.send_keys(PASS)
    # ログイン実施
    button = browser.find_element(By.ID, "loginButton")
    button.click()
    browser.save_screenshot("captures/logined.png")
    print('-> Logined')


def access_meisai(browser, i):
    url = 'https://www.rakuten-card.co.jp/e-navi/members/statement/index.xhtml?tabNo={}'.format(i)
    browser.get(url)


# main_card_numで指定したカードを選択する関数
def select_card(browser, select_card_num, p = None):

    TIMEOUT = 10
    i = 0
    while i == 0:
        try:
            # 現在選択中のカードIDをとってくる。選択できれば終わり。
            WebDriverWait(browser, TIMEOUT).until(
                ec.presence_of_element_located((By.XPATH, '//*[@id="j_idt609"]/div[2]/div/div[2]/div'))
            )

        except TimeoutException:
            i += 1
            print(f"Timeout, Retrying... {i} times")
            time.sleep(10)
            continue

        else:
            i += 1
            print('Successed : selecting card')
            current_card_num_element = browser.find_element(By.XPATH, '//*[@id="j_idt609"]/div[2]/div/div[2]/div')
            card_num_str = current_card_num_element.get_attribute('innerHTML')
            splited_card_num = card_num_str.split(' - ')
            if len(splited_card_num) != 4:
                raise Exception('Invalid CardID Format')
            card_num = splited_card_num[3]
            print(f'Current Selected CardNum=[{card_num}]')
            if select_card_num == card_num:
                print(f'{select_card_num} is selected!')
                return
            # 現在選択しているカードじゃないやつを選ぶ
            card_selector = Select(browser.find_element(By.XPATH, '//*[@id="j_idt609:card"]'))
            if p is None:
                p = 0
            if p == len(card_selector.options):
                raise Exception('Not found card...')
            card_value_to_try = card_selector.options[p].get_attribute('value')
            print(f'Selecting...value={card_value_to_try}')
            card_selector.select_by_value(card_value_to_try)
            # 正しいカードが選択できるまで再帰的にトライする
            select_card(browser, select_card_num, p + 1)

    print("Failed : selecting card in time(%(second)s sec)." % {'second': TIMEOUT})

def get_meisai_title(browser):
    title_element = browser.find_element(By.XPATH, "//*[@id='js-payment-calendar-btn']/span")
    title = title_element.get_attribute('innerHTML')
    print(f'meisai_title={title}')
    return title


def get_meisai_csv_url(browser):
    csv_link_tag = browser.find_element(By.CLASS_NAME, 'stmt-csv-btn')
    href = csv_link_tag.get_attribute('href')
    return href


def get_cookies(browser):
    c = {}
    for cookie in browser.get_cookies():
        name = cookie['name']
        value = cookie['value']
        c[name] = value
    return c


def get_meisai_csv(browser, LOGIN_URL, USER_ID, PASS, CARD_NUM, download_dir_path):
    try:
        login(browser, LOGIN_URL, USER_ID, PASS)
        # 直近三ヶ月のカード利用明細へアクセス
        for main_card_num in [CARD_NUM]:
            for i in range(3):
                # 明細ページへ遷移
                access_meisai(browser, i)
                # カード番号を指定
                select_card(browser, main_card_num)
                # 明細のタイトル名を取得
                meisai_title = get_meisai_title(browser)
                # ダウンロードリンクの取得
                meisai_csv_url = get_meisai_csv_url(browser)
                # requestsで使うためのCookie情報取り出し
                c = get_cookies(browser)
                # 明細年月の取得
                year, month = meisai_title.split('年')
                month = month.split('月')[0]
                yyyymm = year + month
                # CSVダウンロードパス
                download_path = os.path.join(download_dir_path, f'card{main_card_num}_{yyyymm}.csv')
                print(f'Downloading... {download_path}')
                # requestsを利用してデータのダウンロード
                r = requests.get(meisai_csv_url, cookies=c)
                if not os.path.isdir(download_dir_path):
                    os.mkdir(download_dir_path)
                with open(download_path, 'wb') as f:
                        f.write(r.content)
    except Exception as e:
        print(traceback.format_exc())

    browser.quit()

def genrate_comment(amount, BUDGET):
    budget_ratio = amount / int(BUDGET)
    if budget_ratio >= 0 and budget_ratio <= 0.8:
        comment = 'いい感じにゃ😽'

    elif budget_ratio > 0.8 and budget_ratio < 1:
        comment = '気を引き締めるにゃ😾'

    elif budget_ratio >= 1:
        comment = '予算を超えてるにゃ🙀'

    return comment


def aggregate_payment(download_dir_path, BUDGET):

    input_dir = os.path.join(download_dir_path, '*')
    file_list = glob.glob(input_dir)
    df = pd.DataFrame()
    for file_name in file_list:

        df_ = pd.read_csv(file_name)
        df_['payment_month'] = file_name.split('_')[-1].split('.')[0]
        df_ = df_[['利用日', '利用店名・商品名', '支払総額', 'payment_month']].copy()
        df_.columns = ['use_date', 'shop_name', 'payment_amount', 'payment_month']
        df = pd.concat([df, df_], axis=0)

    df = df.loc[~pd.isna(df['use_date']), :]
    df_amount = df.groupby(['payment_month'])['payment_amount'].sum().reset_index()
    df_date = df.groupby(['payment_month']).agg({'use_date':{min, max}}).reset_index()
    df_date.columns = [col1 + '_' + col2 if col2 != '' else col1 for col1, col2 in df_date.columns]

    report_month = df_amount['payment_month'].max()
    report_amount = int(df_amount[df_amount['payment_month'] == report_month]['payment_amount'].values[0])
    report_date_min = df_date[df_date['payment_month'] == report_month]['use_date_min'].values[0]
    report_date_max = df_date[df_date['payment_month'] == report_month]['use_date_max'].values[0]
    report_diff = int(BUDGET) - report_amount
    report_comment = genrate_comment(report_amount, BUDGET)

    fix_month = (pd.to_datetime(report_month+'01') - relativedelta(months=1)).strftime("%Y%m")
    fix_amount = int(df_amount[df_amount['payment_month'] == fix_month]['payment_amount'].values[0])
    fix_comment = genrate_comment(fix_amount, BUDGET)

    financial_report = f'\n【{report_month[-2:]}月】{report_comment}\
                     \n・支払予定:{report_amount:,}円\
                     \n・残額:{report_diff:,}円\
                     \n・期間:\n    {report_date_min}~{report_date_max}\
                     \n【{fix_month[-2:]}月】{fix_comment}\
                     \n・支払確定:{fix_amount:,}円'

    return financial_report


# LINE Notify に通知する
def postLineNotify(token, message=""):

    # LINE Notify API URL
    url = "https://notify-api.line.me/api/notify"

    # リクエストパラメータ
    method = "POST"
    headers = { "Authorization": "Bearer {0}".format(token) }
    payload = {}

    # メッセージ追加
    if message:
        payload["message"] = message

    try:
        payload = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url=url, data=payload, method=method, headers=headers)
        urllib.request.urlopen(req)

    except Exception as e:
        raise e


def main():

    USER_ID = os.environ.get("USER_ID")
    PASS = os.environ.get("PASS")
    LOGIN_URL = os.environ.get("LOGIN_URL")
    CARD_NUM = os.environ.get("CARD_NUM")

    LINE_TOKEN_TEST = os.environ.get("LINE_TOKEN_TEST")  # for development
    LINE_TOKEN_PROD = os.environ.get("LINE_TOKEN_PROD")
    BUDGET = os.environ.get("BUDGET")

    # 明細ダウンロード先の一時フォルダ
    download_dir_path = './tmp'

    options = Options()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--remote-debugging-port=9222')
    # options.binary_location = '/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta'  # for development
    options.add_experimental_option("prefs", {"download.default_directory": download_dir_path})
    browser = Chrome(options=options)


    get_meisai_csv(browser, LOGIN_URL, USER_ID, PASS, CARD_NUM, download_dir_path)
    financial_report = aggregate_payment(download_dir_path, BUDGET)
    # postLineNotify(LINE_TOKEN_TEST, financial_report)  # for development
    postLineNotify(LINE_TOKEN_PROD, financial_report)

    shutil.rmtree(download_dir_path)


if __name__ == '__main__':
    main()
