import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.publickey import PublicKey
import base64
import base58


load_dotenv()

VALIDATORS_APP_API_KEY = os.getenv("VALIDATORS_APP_API_KEY")
PRC_URL = os.getenv("RPC_URL") or "https://api.mainnet-beta.solana.com/"
COMMISSION_CHANGES_DATE_FROM = "2022-01-01T00:00:12"


def get_sfdp_approved_participants():

    solana_client = Client(PRC_URL, Confirmed)
    response = solana_client.get_program_accounts(
        PublicKey('reg8X1V65CSdmrtEjMgnXZk96b9SUSQrJ8n1rP1ZMg7'),
        encoding="base64"
    )
    result = response.value

    approved_participants = {}

    raw_data_list = [program_data.account.data for program_data in result]
    participant_state_map = {1: "PENDING", 2: "REJECTED", 3: "APPROVED"}

    for data in raw_data_list:
        testnet_pubkey = base58.b58encode(data[: 32]).decode('utf-8')
        mb_pubkey = base58.b58encode(data[32: 64]).decode('utf-8')
        participant_state_code = data[64]
        participant_state = participant_state_map.get(participant_state_code)
        if participant_state == "APPROVED":
            approved_participants[mb_pubkey] = {
                "mb_pubkey": mb_pubkey,
                "testnet_pubkey": testnet_pubkey,
                "participant_state_code": participant_state_code,
                "participant_state": participant_state
            }

    return approved_participants


def get_current_epoch():
    solana_client = Client(PRC_URL, Confirmed)
    return solana_client.get_epoch_info().value.epoch


def get_validators_app_data(network="mainnet"):
    url = f"https://www.validators.app/api/v1/validators/{network}.json?order=stake"
    r = requests.get(url, headers={"Token": VALIDATORS_APP_API_KEY})
    return r.json()


def get_commission_changes(network="mainnet"):
    page = 1
    PER_PAGE = 1000
    commission_changes_list = []
    COMMISSION_KEY = "commission_histories"
    while True:
        url = f"https://www.validators.app/api/v1/commission-changes/{network}.json?date_from={COMMISSION_CHANGES_DATE_FROM}&per={PER_PAGE}&page={page}"
        r = requests.get(url, headers={"Token": VALIDATORS_APP_API_KEY})

        if r.status_code != 200:
            break

        result = r.json()

        comm_changes = result[COMMISSION_KEY]

        commission_changes_list = [*commission_changes_list, *comm_changes]

        if len(comm_changes) < PER_PAGE:
            break

        page += 1
    return commission_changes_list


def get_sfdp_set():
    approved_participants = get_sfdp_approved_participants()
    return set(approved_participants.keys())


def filter_for_cheaters(sfdp_set, commission_changes):
    sfdp_cheaters = [commission_hist for commission_hist in commission_changes
                     if commission_hist['account'] in sfdp_set and commission_hist['commission_after'] > 10.0 and commission_hist["commission_before"] is not None]
    return sfdp_cheaters


def create_all_identity_to_vote_key_map(all_validators):
    id_to_vote_key = {}
    for c in all_validators:
        if 'account' in c and 'vote_account' in c:
            id_to_vote_key[c['account']] = c['vote_account']
    return id_to_vote_key


def get_all_transactions_related_to_cheaters(cheaters, commission_changes):
    cheater_id_set = {c['account'] for c in cheaters}
    all_transactions = [
        c for c in commission_changes if c['account'] in cheater_id_set
    ]
    return all_transactions


def squash_all_transactions_in_same_epoch(all_transactions):
    account_to_epoch_map = {}
    for tx in all_transactions:
        if tx['account'] not in account_to_epoch_map:
            account_to_epoch_map[tx['account']] = {}

        if tx['epoch'] not in account_to_epoch_map[tx['account']]:
            account_to_epoch_map[tx['account']][tx['epoch']] = []

        tx['created_at'] = datetime.strptime(
            tx['created_at'], '%Y-%m-%dT%H:%M:%S.%fZ')
        account_to_epoch_map[tx['account']][tx['epoch']].append(tx)

    for account in account_to_epoch_map:
        for epoch in account_to_epoch_map[account]:

            account_to_epoch_map[account][epoch] = sorted(
                account_to_epoch_map[account][epoch], key=lambda d: d['created_at'])

    return account_to_epoch_map

# TODO: Fix this filter function
#
# def filter_out_valid_commission_changers_within_epoch(squashed_transactions):
#     accounts_to_remove = []
#     for account in squashed_transactions:
#         cheating = False
#         for epoch in squashed_transactions[account]:
#             if squashed_transactions[account][epoch][-1]['commission_after'] > 10:
#                 cheating = True
#                 break

#         if not cheating:
#             accounts_to_remove.append(account)

#     for account in accounts_to_remove:
#         del squashed_transactions[account]

#     return squashed_transactions


def print_cheaters_as_csv(squashed_transactions, id_to_vote_key_map, current_epoch):
    for account in squashed_transactions:
        for epoch in squashed_transactions[account]:
            last_tx = squashed_transactions[account][epoch][-1]
            if int(last_tx['commission_after']) > 10 and int(last_tx['epoch']) < current_epoch:
                print(
                    f"{last_tx['account']},{id_to_vote_key_map[last_tx['account']]},{last_tx['created_at']},{last_tx['commission_before']},{last_tx['commission_after']},{last_tx['epoch']},{last_tx['epoch_completion']}")


commission_changes = get_commission_changes()
all_validators = get_validators_app_data()

id_to_vote_key_map = create_all_identity_to_vote_key_map(all_validators)
res = get_commission_changes()
sfdp = get_sfdp_set()

cheaters = filter_for_cheaters(sfdp, commission_changes)
all_transactions = get_all_transactions_related_to_cheaters(
    cheaters, commission_changes)
squashed_transactions = squash_all_transactions_in_same_epoch(all_transactions)
# filtered_and_squashed_transactions = filter_out_valid_commission_changers_within_epoch(
#     squashed_transactions)


current_epoch = get_current_epoch()
print_cheaters_as_csv(squashed_transactions, id_to_vote_key_map, current_epoch)
