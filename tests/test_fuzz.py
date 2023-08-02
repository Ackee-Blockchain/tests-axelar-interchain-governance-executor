import random
from collections import defaultdict
from typing import DefaultDict, Dict
from woke.testing import *
from woke.testing.fuzzing import *
from pytypes.axelarnetwork.axelargmpsdksolidity.contracts.interfaces.IAxelarExecutable import IAxelarExecutable

from pytypes.axelarnetwork.axelargmpsdksolidity.contracts.test.MockGateway import MockGateway
from pytypes.source.contracts.InterchainProposalExecutor import InterchainProposalExecutor
from pytypes.source.contracts.InterchainProposalSender import InterchainProposalSender
from pytypes.source.contracts.lib.InterchainCalls import InterchainCalls
from pytypes.tests.PayloadReceiverMock import PayloadReceiverMock


chain1 = Chain()
chain2 = Chain()


class InterchainProposalFuzzTest(FuzzTest):
    _command_counter: int
    _gateways: Dict[Chain, MockGateway]
    _senders: Dict[Chain, InterchainProposalSender]
    _executors: Dict[Chain, InterchainProposalExecutor]

    _callers: Dict[Chain, List[Account]]
    _payload_receivers: Dict[Chain, List[PayloadReceiverMock]]
    _last_payloads: DefaultDict[Account, bytes]
    _last_values: DefaultDict[Account, int]

    def _relay(self, tx: TransactionAbc) -> None:
        a = chain1.accounts[0].address

        for index, event in enumerate(tx.raw_events):
            if len(event.topics) == 0:
                continue

            if event.topics[0] == MockGateway.ContractCall.selector:
                sender = Abi.decode(["address"], event.topics[1])[0]
                destination_chain_name, destination_address_str, payload = Abi.decode(
                    ["string", "string", "bytes"], event.data
                )
                destination_chain = chain2 if destination_chain_name == "chain2" else chain1
                destination_gw = self._gateways[destination_chain]
                source_chain_name = "chain1" if destination_chain_name == "chain2" else "chain2"
                command_id = self._command_counter.to_bytes(32, "big")

                destination_gw.approveContractCall(Abi.encode(
                    ["string", "string", "address", "bytes32", "bytes32", "uint256"],
                    [source_chain_name, str(sender), Address(destination_address_str), event.topics[2], bytes.fromhex(tx.tx_hash[2:]), index]
                ), command_id, from_=a)

                self._last_relay_tx = IAxelarExecutable(destination_address_str, chain=destination_chain).execute(
                    command_id,
                    source_chain_name,
                    str(sender),
                    payload,
                    from_=a,
                )
                self._command_counter += 1
            elif event.topics[0] == MockGateway.ContractCallWithToken.selector:
                sender = Abi.decode(["address"], event.topics[1])[0]
                destination_chain_name, destination_address_str, payload, symbol, amount = Abi.decode(
                    ["string", "string", "bytes", "string", "uint256"], event.data
                )
                destination_chain = chain2 if destination_chain_name == "chain2" else chain1
                destination_gw = self._gateways[destination_chain]
                source_chain_name = "chain1" if destination_chain_name == "chain2" else "chain2"
                command_id = self._command_counter.to_bytes(32, "big")

                destination_gw.approveContractCallWithMint(Abi.encode(
                    ["string", "string", "address", "bytes32", "string", "uint256", "bytes32", "uint256"],
                    [source_chain_name, str(sender), Address(destination_address_str), event.topics[2], symbol, amount, bytes.fromhex(tx.tx_hash[2:]), index]
                    ), command_id, from_=a)

                self._last_relay_tx = IAxelarExecutable(destination_address_str, chain=destination_chain).executeWithToken(
                    command_id,
                    source_chain_name,
                    str(sender),
                    payload,
                    symbol,
                    amount,
                    from_=a,
                )
                self._command_counter += 1

    def pre_sequence(self) -> None:
        self._command_counter = 0
        chain1.tx_callback = self._relay
        chain2.tx_callback = self._relay

        assert chain1.accounts[0].address == chain2.accounts[0].address
        a = chain1.accounts[0].address

        self._callers = {
            chain1: random.sample(chain1.accounts[1:], 5),
            chain2: random.sample(chain2.accounts[1:], 5),
        }
        self._payload_receivers = {
            chain1: [PayloadReceiverMock.deploy(from_=a, chain=chain1) for _ in range(5)],
            chain2: [PayloadReceiverMock.deploy(from_=a, chain=chain2) for _ in range(5)],
        }
        self._last_payloads = defaultdict(bytes)
        self._last_values = defaultdict(int)

        self._gateways = {
            chain1: MockGateway.deploy(from_=a, chain=chain1),
            chain2: MockGateway.deploy(from_=a, chain=chain2),
        }
        self._senders = {
            chain1: InterchainProposalSender.deploy(self._gateways[chain1], Address.ZERO, from_=a, chain=chain1),
            chain2: InterchainProposalSender.deploy(self._gateways[chain2], Address.ZERO, from_=a, chain=chain2),
        }
        self._executors = {
            chain1: InterchainProposalExecutor.deploy(self._gateways[chain1], a, from_=a, chain=chain1),
            chain2: InterchainProposalExecutor.deploy(self._gateways[chain2], a, from_=a, chain=chain2),
        }

        self._executors[chain1].setWhitelistedProposalSender("chain2", self._senders[chain2].address, True, from_=a)
        self._executors[chain2].setWhitelistedProposalSender("chain1", self._senders[chain1].address, True, from_=a)

        for caller in self._callers[chain1]:
            self._executors[chain2].setWhitelistedProposalCaller("chain1", caller.address, True, from_=a)
        for caller in self._callers[chain2]:
            self._executors[chain1].setWhitelistedProposalCaller("chain2", caller.address, True, from_=a)

    @flow()
    def flow_send_proposals(self) -> None:
        source_chain = random.choice([chain1, chain2])
        destination_chain = chain2 if source_chain == chain1 else chain1
        sender = self._senders[source_chain]
        executor = self._executors[destination_chain]

        proposals = [
            InterchainCalls.InterchainCall(
                f"chain{destination_chain.chain_id}",
                str(executor.address),
                0,
                [
                    InterchainCalls.Call(
                        random.choice(self._payload_receivers[destination_chain]).address,
                        random_int(0, 1000),
                        random_bytes(0, 1000),
                    )
                    for _ in range(random_int(0, 20))
                ],
            )
        ]
        value_sum = sum([call.value for call in proposals[0].calls])
        executor.transact(value=value_sum, from_=destination_chain.accounts[0])

        sender.sendProposals(
            proposals,
            from_=random.choice(self._callers[source_chain]).address,
        )

        for call in proposals[0].calls:
            self._last_payloads[Account(call.target, destination_chain)] = call.callData
            self._last_values[Account(call.target, destination_chain)] = call.value

    @invariant()
    def invariant(self) -> None:
        for chain in [chain1, chain2]:
            for receiver in self._payload_receivers[chain]:
                assert receiver.lastPayload() == self._last_payloads[Account(receiver.address, chain)]
                assert receiver.lastValue() == self._last_values[Account(receiver.address, chain)]


def revert_handler(e: TransactionRevertedError):
    if e.tx is not None:
        print(e.tx.call_trace)
        print(e.tx.console_logs)


@chain1.connect(chain_id=1)
@chain2.connect(chain_id=2)
@on_revert(revert_handler)
def test_fuzz():
    InterchainProposalFuzzTest().run(10, 1_000)
