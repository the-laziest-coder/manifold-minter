import random
import time
import traceback
import web3.exceptions

from termcolor import cprint
from enum import Enum
from pathlib import Path
from datetime import datetime
from retry import retry
from eth_account.account import Account

from logger import Logger, get_telegram_bot_chat_id
from utils import *
from config import *
from vars import *

date_path = datetime.now().strftime('%d-%m-%Y-%H-%M-%S')
results_path = 'results/' + date_path
logs_root = 'logs/'
logs_path = logs_root + date_path
Path(results_path).mkdir(parents=True, exist_ok=True)
Path(logs_path).mkdir(parents=True, exist_ok=True)

logger = Logger(to_console=True, to_file=True, default_file=f'{logs_path}/console_output.txt')


def decimal_to_int(d, n):
    return int(d * (10 ** n))


def int_to_decimal(i, n):
    return i / (10 ** n)


def readable_amount_int(i, n, d=2):
    return round(int_to_decimal(i, n), d)


def wait_next_tx():
    time.sleep(random.uniform(NEXT_TX_MIN_WAIT_TIME, NEXT_TX_MAX_WAIT_TIME))


def _delay(r, *args, **kwargs):
    time.sleep(random.uniform(1, 2))


def get_session(address='', proxy=None):
    sess = requests.Session()
    if proxy is not None:
        sess.proxies = {'http': proxy, 'https': proxy}
    sess.headers = get_default_headers(address)
    sess.hooks['response'].append(_delay)
    return sess


class RunnerException(Exception):

    def __init__(self, message, caused=None):
        super().__init__()
        self.message = message
        self.caused = caused

    def __str__(self):
        if self.caused:
            return self.message + ": " + str(self.caused)
        return self.message


class PendingException(Exception):

    def __init__(self, chain, tx_hash, action):
        super().__init__()
        self.chain = chain
        self.tx_hash = tx_hash
        self.action = action

    def __str__(self):
        return f'{self.action}, chain = {self.chain}, tx_hash = {self.tx_hash.hex()}'

    def get_tx_hash(self):
        return self.tx_hash.hex()


def handle_traceback(msg=''):
    trace = traceback.format_exc()
    logger.print(msg + '\n' + trace, filename=f'{logs_path}/tracebacks.log', to_console=False, store_tg=False)


def runner_func(msg):
    def decorator(func):
        @retry(tries=MAX_TRIES, delay=1.5, backoff=2, jitter=(0, 1), exceptions=RunnerException)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except PendingException:
                raise
            except RunnerException as e:
                raise RunnerException(msg, e)
            except Exception as e:
                handle_traceback(msg)
                raise RunnerException(msg, e)

        return wrapper

    return decorator


@runner_func('Get mint identifier')
def get_mint_identifier(sess):
    resp = sess.get(MANIFOLD_LINK)
    if resp.status_code != 200:
        raise RunnerException(f'status_code = {resp.status_code}, response = {resp.text}')

    identifier = resp.text[resp.text.find('IDENTIFIER:"'):]
    identifier = identifier[identifier.find('"') + 1:]
    identifier = identifier[:identifier.find('"')]

    return identifier


@runner_func('Get mint info')
def get_mint_info(sess, identifier):
    resp = sess.get(f'https://apps.api.manifoldxyz.dev/public/instance/data?id={identifier}')
    if resp.status_code != 200:
        raise RunnerException(f'status_code = {resp.status_code}, response = {resp.text}')
    try:
        data = resp.json()['publicData']
        return data['claimIndex'], data['creatorContractAddress'], data['extensionAddress'], data['network']
    except Exception:
        raise RunnerException(f'response = {resp.text}')


class Status(Enum):
    ALREADY = 1
    PENDING = 2
    SUCCESS = 3
    FAILED = 4


class Runner:

    def __init__(self, private_key, proxy, mint_info):
        if proxy is not None and len(proxy) > 4 and proxy[:4] != 'http':
            proxy = 'http://' + proxy
        self.proxy = proxy

        self.w3s = {chain: get_w3(chain, proxy=self.proxy) for chain in RPCs}

        self.private_key = private_key
        self.address = Account().from_key(private_key).address

        self.sess = get_session(self.address, self.proxy)

        self.mint_info = mint_info

    def w3(self, chain):
        return self.w3s[chain]

    def tx_verification(self, chain, tx_hash, action=None):
        action_print = action + ' - ' if action else ''
        logger.print(f'{action_print}Tx was sent')
        try:
            transaction_data = self.w3(chain).eth.wait_for_transaction_receipt(tx_hash)
            status = transaction_data.get('status')
            if status is not None and status == 1:
                logger.print(f'{action_print}Successful tx: {SCANS[chain]}/tx/{tx_hash.hex()}')
            else:
                raise RunnerException(f'{action_print}Tx status = {status}, chain = {chain}, tx_hash = {tx_hash.hex()}')
        except web3.exceptions.TimeExhausted:
            raise PendingException(chain, tx_hash, action_print[:-3])

    def build_and_send_tx(self, w3, func, action, value=0):
        return build_and_send_tx(w3, self.address, self.private_key, func, value, self.tx_verification, action)

    @runner_func('Mint')
    def mint(self, mint_contract_address, identifier, creator_contract_address, chain):
        w3 = self.w3(chain)

        mint_contract_address = Web3.to_checksum_address(mint_contract_address)
        creator_contract_address = Web3.to_checksum_address(creator_contract_address)

        contract = w3.eth.contract(mint_contract_address, abi=MANIFOLD_MINT_ABI)

        claim_data = contract.functions.getClaim(creator_contract_address, identifier).call()
        wallet_max = claim_data[2]
        cost = claim_data[-3]
        merkle_proof = []
        mint_index = 0

        wallet_mints = contract.functions.getTotalMints(self.address, creator_contract_address, identifier).call()
        if wallet_mints >= wallet_max:
            return Status.ALREADY

        manifold_fee = contract.functions.MINT_FEE().call()

        mint_args = (creator_contract_address, identifier, mint_index, merkle_proof, self.address)

        self.build_and_send_tx(
            w3,
            contract.functions.mint(*mint_args),
            action='Mint',
            value=cost + manifold_fee
        )

        return Status.SUCCESS

    def run(self):
        logger.print(self.address)

        identifier, creator_contract_address, mint_contract_address, network = self.mint_info

        return self.mint(mint_contract_address, identifier, creator_contract_address, CHAIN_NAMES[network])


def wait_next_run(idx, runs_count):
    wait = random.randint(
        int(NEXT_ADDRESS_MIN_WAIT_TIME * 60),
        int(NEXT_ADDRESS_MAX_WAIT_TIME * 60)
    )

    done_msg = f'Done: {idx}/{runs_count}'
    waiting_msg = 'Waiting for next run for {:.2f} minutes'.format(wait / 60)

    cprint('\n#########################################\n#', 'cyan', end='')
    cprint(done_msg.center(39), 'magenta', end='')
    cprint('#\n#########################################', 'cyan', end='')

    tg_msg = done_msg

    cprint('\n# ', 'cyan', end='')
    cprint(waiting_msg, 'magenta', end='')
    cprint(' #\n#########################################\n', 'cyan')
    tg_msg += '. ' + waiting_msg

    logger.send_tg(tg_msg)

    time.sleep(wait)


def write_result(filename, account):
    with open(f'{results_path}/{filename}', 'a') as file:
        file.write(f'{"|".join([str(a) for a in list(account)])}\n')


def log_run(address, account, status, exc=None, msg=''):
    exc_msg = '' if exc is None else str(exc)

    account = (address, ) + account

    if status == Status.ALREADY:
        summary_msg = 'Already minted'
        color = 'green'
        write_result('already.txt', account)
    elif status == Status.PENDING:
        summary_msg = 'Tx in pending: ' + exc_msg
        color = 'yellow'
        write_result('pending.txt', account)
    elif status == Status.SUCCESS:
        summary_msg = 'Run success'
        color = 'green'
        write_result('success.txt', account)
    else:
        summary_msg = 'Run failed: ' + exc_msg
        color = 'red'
        write_result('failed.txt', account)

    logger.print(summary_msg, color=color)

    if msg != '':
        logger.print(msg, color=color)

    logger.send_tg_stored()


def main():
    if GET_TELEGRAM_CHAT_ID:
        get_telegram_bot_chat_id()
        exit(0)

    random.seed(int(datetime.now().timestamp()))

    with open('files/wallets.txt', 'r') as file:
        wallets = file.read().splitlines()
    with open('files/proxies.txt', 'r') as file:
        proxies = file.read().splitlines()

    if len(proxies) == 0:
        proxies = [None] * len(wallets)
    if len(proxies) != len(wallets):
        cprint('Proxies count doesn\'t match wallets count. Add proxies or leave proxies file empty', 'red')
        return

    sess = get_session()
    mint_info = get_mint_info(sess, get_mint_identifier(sess))
    cprint(f'Network = {CHAIN_NAMES[mint_info[3]]}\n'
           f'Mint contract = {mint_info[2]}\n'
           f'NFT contract = {mint_info[1]}\n'
           f'Identifier = {mint_info[0]}\n')
    wait_next_tx()

    queue = list(zip(wallets, proxies))
    random.shuffle(queue)

    idx, runs_count = 0, len(queue)

    while len(queue) != 0:

        if idx != 0:
            wait_next_run(idx, runs_count)

        account = queue.pop(0)

        wallet, proxy = account

        if wallet.find(';') == -1:
            key = wallet
        else:
            key = wallet.split(';')[1]

        runner = Runner(key, proxy, mint_info)

        address = runner.address

        exc = None

        try:
            status = runner.run()
        except PendingException as e:
            status = Status.PENDING
            exc = e
        except RunnerException as e:
            status = Status.FAILED
            exc = e
        except Exception as e:
            handle_traceback()
            status = Status.FAILED
            exc = e

        log_run(address, account, status, exc=exc)

        idx += 1

    cprint('\n#########################################\n#', 'cyan', end='')
    cprint(f'Finished'.center(39), 'magenta', end='')
    cprint('#\n#########################################', 'cyan')


if __name__ == '__main__':
    cprint('###########################################################', 'cyan')
    cprint('#######################', 'cyan', end='')
    cprint(' By @timfame ', 'magenta', end='')
    cprint('#######################', 'cyan')
    cprint('###########################################################\n', 'cyan')

    main()
