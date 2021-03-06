from typing import Any, Union, cast
from boa3.builtin import NeoMetadata, metadata, public
from boa3.builtin.contract import Nep17TransferEvent, abort
from boa3.builtin.interop.blockchain import get_contract, Transaction
from boa3.builtin.interop.contract import call_contract
from boa3.builtin.interop.runtime import calling_script_hash, check_witness, script_container
from boa3.builtin.interop.storage import delete, get, put
from boa3.builtin.type import UInt160


# -------------------------------------------
# METADATA
# -------------------------------------------

@metadata
def manifest_metadata() -> NeoMetadata:
    """
    Defines this smart contract's metadata information
    """
    meta = NeoMetadata()
    meta.author = 'MyWish'
    meta.email = 'noreply@mywish.io'
    meta.description = 'MyWish NEP17 Standard Token'
    meta.version = "v1.0"
    return meta

# ---------------------------------
# CONTRACT GLOBALS
# ---------------------------------


OWNER = UInt160({{owner}})
TOKEN_DECIMALS = {{ token_decimals }}
TOKEN_SYMBOL = '{{ token_symbol }}'
TOTAL_SUPPLY = b'total_supply'
CONTINUE_MINTING = b'continue_minting'

{% if (holders is defined) and holders %}
HOLDERS = {
{% for item in holders %}
UInt160({{ item['address'] }}): {{ item['amount'] }},
{% endfor %}
}
{% endif %}



# ---------------------------------
# EVENTS
# ---------------------------------

on_transfer = Nep17TransferEvent

# ---------------------------------
# Methods
# ---------------------------------


@public
def symbol() -> str:
    """
    Gets the symbols of the token.
    :return: a short string representing symbol of the token managed in this contract.
    """
    return TOKEN_SYMBOL


@public
def decimals() -> int:
    """
    Gets the amount of decimals used by the token.
    :return: the number of decimals used by the token.
    """
    return TOKEN_DECIMALS


@public
def totalSupply() -> int:
    """
    Gets the total token supply deployed in the system.
    :return: the total token supply in the system.
    """
    return get(TOTAL_SUPPLY).to_int()


@public
def balanceOf(account: UInt160) -> int:
    """
    Get the current balance of an address
    :param account: the account address to retrieve the balance for
    :type account: UInt160
    """
    assert len(account) == 20
    return get(account).to_int()


@public
def transfer(from_address: UInt160, to_address: UInt160, amount: int, data: Any) -> bool:
    """
    Transfers an amount of NEP17 tokens from one account to another
    If the method succeeds, it must fire the `Transfer` event and must return true, even if the amount is 0,
    or from and to are the same address.
    :param from_address: the address to transfer from
    :type from_address: UInt160
    :param to_address: the address to transfer to
    :type to_address: UInt160
    :param amount: the amount of NEP17 tokens to transfer
    :type amount: int
    :param data: whatever data is pertinent to the onPayment method
    :type data: Any
    :return: whether the transfer was successful
    :raise AssertionError: raised if `from_address` or `to_address` length is not 20 or if `amount` is less than zero.
    """
    # the parameters from and to should be 20-byte addresses. If not, this method should throw an exception.
    assert len(from_address) == 20 and len(to_address) == 20
    # the parameter amount must be greater than or equal to 0. If not, this method should throw an exception.
    assert amount >= 0

    # The function MUST return false if the from account balance does not have enough tokens to spend.
    from_balance = get(from_address).to_int()
    if from_balance < amount:
        return False

    # The function should check whether the from address equals the caller contract hash.
    # If so, the transfer should be processed;
    # If not, the function should use the check_witness to verify the transfer.
    if from_address != calling_script_hash:
        if not check_witness(from_address):
            return False

    # skip balance changes if transferring to yourself or transferring 0 cryptocurrency
    if from_address != to_address and amount != 0:
        if from_balance == amount:
            delete(from_address)
        else:
            put(from_address, from_balance - amount)

        to_balance = get(to_address).to_int()
        put(to_address, to_balance + amount)

    # if the method succeeds, it must fire the transfer event
    on_transfer(from_address, to_address, amount)
    # if the to_address is a smart contract, it must call the contracts onPayment
    post_transfer(from_address, to_address, amount, data)
    # and then it must return true
    return True


def post_transfer(from_address: Union[UInt160, None], to_address: Union[UInt160, None], amount: int, data: Any):
    """
    Checks if the one receiving NEP17 tokens is a smart contract and if it's one the onPayment method will be called
    :param from_address: the address of the sender
    :type from_address: UInt160
    :param to_address: the address of the receiver
    :type to_address: UInt160
    :param amount: the amount of cryptocurrency that is being sent
    :type amount: int
    :param data: any pertinent data that might validate the transaction
    :type data: Any
    """
    if not isinstance(to_address, None):
        contract = get_contract(to_address)
        if not isinstance(contract, None):
            call_contract(to_address, 'onNEP17Payment', [from_address, amount, data])


@public
def finishMinting() -> bool:
    continue_minting = get(CONTINUE_MINTING).to_bool()
    if not continue_minting:
        return False

    put(CONTINUE_MINTING, False)
    return True



@public
def mint(account: UInt160, amount: int):
    """
    Mints new tokens.
    :param account: the address of the account that is sending cryptocurrency to this contract
    :type account: UInt160
    :param amount: the amount of gas to be refunded
    :type amount: int
    :raise AssertionError: raised if amount is less than than 0
    """
    continue_minting = get(CONTINUE_MINTING).to_bool()
    assert amount >= 0 and check_witness(OWNER) and continue_minting
    if amount != 0:
        current_total_supply = totalSupply()
        account_balance = balanceOf(account)

        put(TOTAL_SUPPLY, current_total_supply + amount)
        put(account, account_balance + amount)

        on_transfer(None, account, amount)
        post_transfer(None, account, amount, None)


@public
def burn(amount: int):
    """
    Burns tokens.
    :param amount: the amount to be burned
    :type amount: int
    :raise AssertionError: raised if amount is less than than 0
    """
    assert amount >= 0
    if amount != 0:
        tx = cast(Transaction, script_container)
        account = tx.sender
        account_balance = balanceOf(account)
        assert account_balance >= amount

        current_total_supply = totalSupply()
        put(TOTAL_SUPPLY, current_total_supply - amount)

        if account_balance == amount:
            delete(account)
        else:
            put(account, account_balance - amount)

        on_transfer(account, None, amount)
        post_transfer(account, None, amount, None)


@public
def _deploy(data: Any, update: bool):
    total_supply = 0
{% if (holders is defined) and holders %}
    for holder in HOLDERS.keys():
        amount = HOLDERS[holder]
        put(holder, amount)
        on_transfer(None, holder, amount)
        total_supply += amount
{% endif %}

    put(CONTINUE_MINTING, {{ continue_minting }})
    put(TOTAL_SUPPLY, total_supply)


@public
def onNEP17Payment(from_address: UInt160, amount: int, data: Any):
    """
    This contract is currently not accepting any transfers.
    :param from_address: the address of the one who is trying to send cryptocurrency to this smart contract
    :type from_address: UInt160
    :param amount: the amount of cryptocurrency that is being sent to the this smart contract
    :type amount: int
    :param data: any pertinent data that might validate the transaction
    :type data: Any
    """
    abort()
