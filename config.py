MANIFOLD_LINK = 'https://app.manifold.xyz/c/soundxyz'

###############################################################################################################

RPCs = {
    'Ethereum':  'https://eth.llamarpc.com',
    'Optimism':  'https://rpc.ankr.com/optimism',
    'BSC':       'https://rpc.ankr.com/bsc',
    'Gnosis':    'https://rpc.gnosischain.com',
    'Polygon':   'https://polygon.llamarpc.com',
    'Fantom':    'https://rpc.fantom.network',
    'Arbitrum':  'https://arb1.arbitrum.io/rpc',
    'Avalanche': 'https://avalanche-c-chain.publicnode.com',
    'zkSync':    'https://mainnet.era.zksync.io',
    'zkEVM':     'https://rpc.ankr.com/polygon_zkevm',
}

###############################################################################################################

# Время ожидания между выполнением разных акков рандомное в указанном диапазоне
NEXT_ADDRESS_MIN_WAIT_TIME = 1  # В минутах
NEXT_ADDRESS_MAX_WAIT_TIME = 2  # В минутах

# Время ожидания между действиями одного аккаунта
NEXT_TX_MIN_WAIT_TIME = 6   # В секундах
NEXT_TX_MAX_WAIT_TIME = 12  # В секундах

# Максимальное кол-во попыток сделать запрос/транзакцию если они фейлятся
MAX_TRIES = 3

###############################################################################################################

# Множитель газа
GAS_PRICE_MULT = 1.1

###############################################################################################################

# Токен и chat id бота в тг. Можно оставить пустым.
TELEGRAM_BOT_TOKEN = ''
TELEGRAM_CHAT_ID = 0
# При True, скрипт только выдает ваш chat id для отправки сообщений в боте.
GET_TELEGRAM_CHAT_ID = False
