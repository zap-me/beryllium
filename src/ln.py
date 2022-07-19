from decimal import Decimal
import os
import datetime

from pyln.client import LightningRpc

import assets

def _msat_to_sat(msats):
    return int(int(msats) / 1000)

def _sat_to_msat(sats):
    return int(sats) * 1000

class LnRpc():
    def __init__(self):
        if 'LN_RPC_FILE' in os.environ:
            self.instance = LightningRpc(os.environ['LN_RPC_FILE'])
        else:
            self.instance = LightningRpc("/etc/lightning/lightning-rpc")

    def get_info(self):
        return self.instance.getinfo()

    def list_nodes(self):
        return self.instance.listnodes()

    def connect_node(self, node_address):
        return self.instance.connect(node_address)

    def list_peers(self):
        return self.instance.listpeers()

    #
    # LN
    #

    def invoice(self, sats: int, label: str, msg: str) -> dict:
        # create a LN invoice
        return self.instance.invoice(_sat_to_msat(sats), label, msg)

    def invoice_status(self, bolt11: str) -> dict:
        return self.instance.listinvoices(invstring=bolt11)

    def pay(self, bolt11: str) -> dict:
        # pay a bolt11 invoice
        assert assets.BTCLN.withdraw_fee_fixed is False
        max_fee_percent = str(assets.BTCLN.withdraw_fee * Decimal(100))
        result = self.instance.pay(bolt11, maxfeepercent=max_fee_percent)
        result["sats_sent"] = _msat_to_sat(result["msatoshi_sent"])
        return result

    def pay_status(self, bolt11: str) -> dict:
        # show the status of a specific paid bolt11 invoice
        return self.instance.listpays(bolt11=bolt11)

    def pay_status_from_hash(self, payment_hash: str) -> dict:
        # show the status of a specific payment hash
        return self.instance.listpays(payment_hash=payment_hash)

    def lastpay_index(self) -> int:
        result = self.instance.listinvoices()
        invoices = result['invoices']
        current_pay_index = 0
        for invoice in invoices:
            if invoice['status'] == 'paid':
                pay_index = invoice['pay_index']
                if pay_index > current_pay_index:
                    current_pay_index = pay_index
        return current_pay_index

    def list_paid(self):
        # show the status of all paid bolt11 invoice
        results = []
        pays = self.instance.listpays()
        for pay in pays["pays"]:
            created_at = pay["created_at"]
            date = datetime.datetime.fromtimestamp(created_at)
            status = pay["status"]
            amount_msat = pay["amount_sent_msat"].millisatoshis
            amount_sats = _msat_to_sat(amount_msat)
            results.append({"created_at": created_at,
                            "date": date,
                            "status": status,
                            "amount_msat": amount_msat,
                            "amount_sats": amount_sats})
        return results

    def decode_bolt11(self, bolt11: str) -> dict:
        result = self.instance.decodepay(bolt11)
        sats = _msat_to_sat(result["amount_msat"].millisatoshis)
        result['amount_sat'] = sats
        return result

    def wait_any_invoice(self, lastpay_index=0, timeout: int | None = None) -> dict:
        return self.instance.waitanyinvoice(lastpay_index=lastpay_index, timeout=timeout)

    def list_channels(self):
        return self.instance.listchannels()

    def rebalance_channel(self, oscid: str, iscid: str, amount_sat: int):
        return self.instance.rebalance(oscid, iscid, _sat_to_msat(amount_sat))

    def fee_rates(self):
        # get fee rates in unit of sats per 1000 virtual bytes
        return self.instance.feerates("perkb")

    def key_send(self, node_id: str, sats: int):
        return self.instance.keysend(node_id, _sat_to_msat(sats))

    def list_forwards(self):
        return self.instance.listforwards()

    def list_invoices(self):
        results = []
        result_invoices = self.instance.listinvoices()
        for invoice in result_invoices["invoices"]:
            label = invoice["label"]
            description = invoice["description"]
            payment_hash = invoice["payment_hash"]
            expires_at = invoice["expires_at"]
            bolt11 = invoice["bolt11"]
            pay_index = None
            amount_received_msat = None
            paid_at = None
            paid_date = None
            payment_preimage = None
            status = invoice["status"]
            if status == 'paid':
                amount_msat = invoice["amount_msat"]
                amount_sats = _msat_to_sat(amount_msat)
                pay_index = invoice["pay_index"]
                amount_received_msat = invoice["amount_received_msat"]
                amount_received_sats = _msat_to_sat(amount_received_msat)
                paid_at = invoice["paid_at"]
                paid_date = datetime.datetime.fromtimestamp(paid_at)
                payment_preimage = invoice["payment_preimage"]
                results.append({"paid_at": paid_at, "paid_date": paid_date, "description": description, "status": status, "amount_msat": amount_msat, "amount_sats": amount_sats, "pay_index": pay_index, "amount_received_msat": amount_received_msat, "amount_received_sats": amount_received_sats, "payment_preimage": payment_preimage, "bolt11": bolt11, "expires_at": expires_at, "payment_hash": payment_hash, "label": label})
        return results

    def list_sendpays(self):
        results = []
        result_sendpays = self.instance.listsendpays()
        for sendpay in result_sendpays["payments"]:
            payment_hash = sendpay["payment_hash"]
            status = sendpay["status"]
            created_at = sendpay["created_at"]
            amount_sent_msat = sendpay["amount_sent_msat"]
            amount_sent_sats = _msat_to_sat(amount_sent_msat)
            amount_msat = sendpay["amount_msat"]
            amount_sats = _msat_to_sat(amount_msat)
            destination = sendpay["destination"]
            label = ""
            if label:
                label = sendpay["label"]
            bolt11 = None
            if bolt11:
                bolt11 = sendpay["bolt11"]
            groupid = None
            if groupid:
                groupid = sendpay["groupid"]
            payment_preimage = None
            fees_sats = None
            if status == "complete":
                paid_at = created_at
                paid_date = datetime.datetime.fromtimestamp(paid_at)
                payment_preimage = sendpay["payment_hash"]
                fees_sats = amount_sent_sats - amount_sats
                results.append({"paid_at": paid_at, "paid_date": paid_date, "status": status, "amount_msat": amount_msat, "amount_sats": amount_sats, "amount_sent_msat": amount_sent_msat, "amount_sent_sats": amount_sent_sats, "destination": destination, "label": label, "bolt11": bolt11, "payment_preimage": payment_preimage, "payment_hash": payment_hash, "groupid": groupid, "fees_sats": fees_sats})
        return results

    def disconnect_peer(self, peer_id):
        return self.instance.disconnect(peer_id)

    #
    # Onchain
    #

    def list_funds(self) -> dict:
        funds = self.instance.listfunds()
        msats_largest_channel = 0
        msats_channels = 0
        msats_largest_channel_theirs = 0
        msats_channels_theirs = 0
        msats_onchain = 0
        msats_onchain_unconfirmed = 0
        msats_onchain_reserved = 0
        sats_largest_channel = 0
        sats_channels = 0
        sats_largest_channel_theirs = 0
        sats_channels_theirs = 0
        sats_onchain = 0
        sats_onchain_unconfirmed = 0
        sats_onchain_reserved = 0
        # Only shows after the very first transaction otherwise errors.
        for chan in funds["channels"]:
            if chan["state"] == "CHANNELD_NORMAL":
                msats_channel = chan["our_amount_msat"].millisatoshis
                if msats_channel > msats_largest_channel:
                    msats_largest_channel = msats_channel
                msats_channels += msats_channel
                msats_channel_theirs = chan["amount_msat"].millisatoshis - chan["our_amount_msat"].millisatoshis
                if msats_channel_theirs > msats_largest_channel_theirs:
                    msats_largest_channel_theirs = msats_channel_theirs
                msats_channels_theirs += msats_channel_theirs
        sats_largest_channel = _msat_to_sat(msats_largest_channel)
        sats_channels = _msat_to_sat(msats_channels)
        sats_largest_channel_theirs = _msat_to_sat(msats_largest_channel_theirs)
        sats_channels_theirs = _msat_to_sat(msats_channels_theirs)
        for output in funds["outputs"]:
            if output["status"] == "confirmed" and not output["reserved"]:
                msats_onchain += output["amount_msat"].millisatoshis
            if output["status"] == "unconfirmed":
                msats_onchain_unconfirmed += output["amount_msat"].millisatoshis
            if output["reserved"]:
                msats_onchain_reserved += output["amount_msat"].millisatoshis
        sats_onchain = _msat_to_sat(msats_onchain)
        sats_onchain_unconfirmed = _msat_to_sat(msats_onchain_unconfirmed)
        sats_onchain_reserved = _msat_to_sat(msats_onchain_reserved)
        return dict(funds=funds, msats_largest_channel=msats_largest_channel, msats_channels=msats_channels, msats_largest_channel_theirs=msats_largest_channel_theirs, msats_channels_theirs=msats_channels_theirs, msats_onchain=msats_onchain, msats_onchain_unconfirmed=msats_onchain_unconfirmed, msats_onchain_reserved=msats_onchain_reserved, sats_largest_channel=sats_largest_channel, sats_channels=sats_channels, sats_channels_theirs=sats_channels_theirs, sats_largest_channel_theirs=sats_largest_channel_theirs, sats_onchain=sats_onchain, sats_onchain_unconfirmed=sats_onchain_unconfirmed, sats_onchain_reserved=sats_onchain_reserved)

    def fund_channel(self, node_id: str, amount: str):
        return self.instance.fundchannel(node_id, amount)

    def close_channel(self, channel_id: str):
        return self.instance.close(channel_id)

    def new_address(self, address_type: str):
        # return a bech32 address
        return self.instance.newaddr(addresstype=address_type)

    def list_txs(self):
        return self.instance.listtransactions()

    def multi_withdraw(self, outputs: list[dict[str, str]]):
        # outputs is in form {"address" : amount}
        return self.instance.multiwithdraw(outputs)

    def prepare_psbt(self, outputs: list[dict[str, str]]):
        return self.instance.txprepare(outputs)

    def sign_psbt(self, unsigned_psbt: str):
        return self.instance.signpsbt(unsigned_psbt)

    def send_psbt(self, signed_psbt: str):
        return self.instance.sendpsbt(signed_psbt)

    def list_addrs(self):
        return self.instance.call('dev-listaddrs')
