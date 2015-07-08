__author__ = 'Aaron Hosford'

import random

from xcs import ClassifierSet
from xcs import bitstrings
from xcs import scenarios













class CompositeMatchSet:

    def __init__(self, model, situation, extended_situation, match_sets):
        self._model = model
        self._situation = situation
        self._extended_situation = extended_situation
        self._match_sets = tuple(match_sets)

        self._best_action = self._extended_situation[len(situation):]
        self._best_action_sets = [match_set[bit] for match_set, bit in zip(self._match_sets, self._best_action)]

        total = sum(action_set.prediction * action_set.prediction_weight for action_set in self._best_action_sets)
        weight = sum(action_set.prediction_weight for action_set in self._best_action_sets)

        self._best_prediction = total / (weight or 1)

        self._selected_action = None
        self._prediction = None
        self._payoff = 0
        self._closed = False

    @property
    def model(self):
        return self._model

    @property
    def situation(self):
        return self._situation

    @property
    def algorithm(self):
        return self._model.algorithm

    @property
    def time_stamp(self):
        return self._match_sets[0].time_stamp

    @property
    def best_prediction(self):
        return self._best_prediction

    @property
    def best_actions(self):
        return [self._best_action]

    def select_action(self):
        if self._selected_action is not None:
            raise ValueError("The action has already been selected.")
        for match_set in self._match_sets:
            match_set.select_action()
        self._selected_action = bitstrings.BitString([match_set.selected_action for match_set in self._match_sets])
        return self._selected_action

    def _get_selected_action(self):
        return self._selected_action

    def _set_selected_action(self, action):
        assert isinstance(action, (bitstrings.BitString, bitstrings.BitCondition))
        assert len(action) == len(self._match_sets)

        if self._selected_action is not None:
            raise ValueError("The action has already been selected.")
        self._selected_action = action

        for match_set, bit in zip(self._match_sets, self._selected_action):
            match_set.selected_action = bit

    selected_action = property(
        _get_selected_action,
        _set_selected_action,
        doc="""The action which was selected for execution and which
            deserves credit for whatever payoff is received. This will be
            None if no action has been selected. An action can be selected
            by calling match_set.select_action() or by assigning directly
            to this property. Note, however, that if an action has already
            been selected, attempting to assign to this property will cause
            a ValueError to be raised."""
    )

    @property
    def prediction(self):
        if self._selected_action is None:
            return None
        if self._prediction is None:
            if self._selected_action == self._best_action:
                self._prediction = self._best_prediction
            else:
                total = sum(match_set.prediction * match_set.prediction_weight for match_set in self._match_sets)
                weight = sum(match_set.prediction_weight for match_set in self._match_sets)
                self._prediction = total / (weight or 1)
        return self._prediction

    def _get_payoff(self):
        return self._payoff

    def _set_payoff(self, payoff):
        if self._selected_action is None:
            raise ValueError("The action has not been selected yet.")
        if self._closed:
            raise ValueError("The payoff for this match set has already"
                             "been applied.")
        if isinstance(payoff, (int, float)):
            self._payoff = float(payoff)
        else:
            assert len(payoff) == len(self._selected_action)
            self._payoff = tuple(payoff)

    payoff = property(
        _get_payoff,
        _set_payoff,
        doc="""The payoff received for the selected action. This starts out
            as 0 and should be assigned or incremented to reflect the total
            payoff (both immediate reward and discounted expected future
            reward) in response to the selected action. Attempting to
            modify this property before an action has been selected or
            after the payoff has been applied will result in a ValueError.
            """
    )

    def pay(self, predecessor):
        assert predecessor is None or isinstance(predecessor, CompositeMatchSet)

        if predecessor is not None:
            # TODO: Does it really make sense to use prediction_weight here?
            total = sum(match_set.algorithm.get_future_expectation(match_set) * match_set.prediction_weight for match_set in self._match_sets)
            weight = sum(match_set.prediction_weight for match_set in self._match_sets)
            expectation = total / (weight or 1)
            predecessor.payoff += expectation

    def apply_payoff(self):
        if self._selected_action is None:
            raise ValueError("The action has not been selected yet.")
        if self._closed:
            raise ValueError("The payoff for this match set has already"
                             "been applied.")
        if isinstance(self._payoff, tuple):
            for match_set, payoff in zip(self._match_sets, self._payoff):
                match_set.payoff = payoff
                match_set.apply_payoff()
        else:
            for match_set in self._match_sets:
                match_set.payoff = self._payoff
                match_set.apply_payoff()
        self._closed = True

    @property
    def closed(self):
        return self._closed


class CompositeClassifierSet:

    def __init__(self, algorithm, action_size):
        self._algorithm = algorithm
        self._classifier_sets = tuple(ClassifierSet(algorithm, (True, False)) for _ in range(action_size))

    def extend_actions(self, count=1):
        self._classifier_sets += tuple(ClassifierSet(self._algorithm, (True, False)) for _ in range(count))

    def extend_situations(self, count=1):
        classifier_sets = []
        for classifier_set in self._classifier_sets:
            new_cs = ClassifierSet(self._algorithm, (True, False))
            for rule in classifier_set:
                new_cs.add(rule.extend(count))  # TODO: This only works for XCS. What's the right way to do this so any bit-based algorithm is covered?
            classifier_sets.append(new_cs)
        self._classifier_sets = tuple(classifier_sets)

    @property
    def algorithm(self):
        return self._algorithm

    @property
    def action_size(self):
        return len(self._classifier_sets)

    @property
    def classifier_sets(self):
        return self._classifier_sets

    @property
    def time_stamp(self):
        return self._classifier_sets[0].time_stamp

    def match(self, situation):
        if not isinstance(situation, (bitstrings.BitString, bitstrings.BitCondition)):
            situation = bitstrings.BitString(situation)

        extended_situation = situation
        match_sets = []

        for classifier_set in self._classifier_sets:
            match = classifier_set.match(extended_situation)
            bit = random.choice(match.best_actions)
            extended_situation += bitstrings.BitString(bit, 1)
            match_sets.append(match)

        return CompositeMatchSet(self, situation, extended_situation, match_sets)

    def run(self, scenario, learn=True):
        assert isinstance(scenario, scenarios.Scenario)

        previous_match_set = None

        # Repeat until the scenario has run its course.
        while scenario.more():
            # Gather information about the current state of the
            # environment.
            situation = scenario.sense()

            # Determine which rules match the current situation.
            match_set = self.match(situation)

            # Select the best action for the current situation (or a random
            # one, if we are on an exploration step).
            match_set.select_action()

            # Perform the selected action
            # and find out what the received reward was.
            reward = scenario.execute(match_set.selected_action)

            # If the scenario is dynamic, don't immediately apply the
            # reward; instead, wait until the next iteration and factor in
            # not only the reward that was received on the previous step,
            # but the (discounted) reward that is expected going forward
            # given the resulting situation observed after the action was
            # taken. This is a classic feature of temporal difference (TD)
            # algorithms, which acts to stitch together a general picture
            # of the future expected reward without actually waiting the
            # full duration to find out what it will be.
            if learn:
                # Ensure we are not trying to learn in a non-learning
                # scenario.
                assert reward is not None

                if scenario.is_dynamic:
                    if previous_match_set is not None:
                        match_set.pay(previous_match_set)
                        previous_match_set.apply_payoff()
                    match_set.payoff = reward

                    # Remember the current reward and match set for the
                    # next iteration.
                    previous_match_set = match_set
                else:
                    match_set.payoff = reward
                    match_set.apply_payoff()

        # This serves to tie off the final stitch. The last action taken
        # gets only the immediate reward; there is no future reward
        # expected.
        if learn and previous_match_set is not None:
            previous_match_set.apply_payoff()




class ClassifierSetAutoEncoder:

    def __init__(self, encoder_algorithm, input_size, decoder_algorithm, encoding_size):
        self._encoder = CompositeClassifierSet(encoder_algorithm, encoding_size)
        self._decoder = CompositeClassifierSet(decoder_algorithm, input_size)

        #weights = []
        #for _ in range(encoding_size):
        #    weight_map = [.01 + random.random() for _ in range(input_size)]
        #    total = sum(weight_map)
        #    weight_map = [weight / total for weight in weight_map]
        #    weights.append(weight_map)
        #self._weights = weights

        #self._ratio = input_size // encoding_size + 2

        ## Randomly distribute weights, but do so in a way that is
        ## even both for encoded and decoded bits.
        ## {encoded: {decoded: weight}}
        #weight_map = {e: {d: 0 for d in range(input_size)} for e in range(encoding_size)}
        #for d in range(input_size):
        #    weights = {e: 1 + random.randrange(2) for e in range(encoding_size)}
        #    total = sum(weights.values())
        #    for e in weights:
        #        weights[e] /= total
        #    for e in range(encoding_size):
        #        weight_map[e][d] = weights[e]
        #max_total = max(sum(weight_map[e].values()) for e in weight_map)
        #for e in weight_map:
        #    addition = (max_total - sum(weight_map[e].values())) / input_size
        #    for d in weight_map[e]:
        #        weight_map[e][d] += addition
        #    weight_map[e] = [weight for d, weight in sorted(weight_map[e].items())]
        #self._weights = tuple(tuple(weights) for e, weights in sorted(weight_map.items()))
        #
        #for weights in self._weights:
        #    print(weights)
        #print(min(sum(weights) for weights in self._weights), max(sum(weights) for weights in self._weights))
        #print(min(sum(weights[e] for weights in self._weights) for e in range(encoding_size)), max(sum(weights[e] for weights in self._weights) for e in range(encoding_size)))

    @property
    def encoder(self):
        return self._encoder

    @property
    def decoder(self):
        return self._decoder

    def extend(self, count=1):
        self._encoder.extend_actions(count)
        self._decoder.extend_situations(count)

    def train(self, bits):
        assert isinstance(bits, (bitstrings.BitString, bitstrings.BitCondition))
        assert len(bits) == self._decoder.action_size

        encoding_match = self._encoder.match(bits)
        encoding_match.select_action()

        decoding_match = self._decoder.match(encoding_match.selected_action)
        decoding_match.select_action()

        reconstructed_bits = decoding_match.selected_action

        correct = bits ^ ~reconstructed_bits
        #score = correct.count() / len(correct)

        non_exploring = [bit for index, bit in enumerate(correct) if decoding_match.selected_action[index] == decoding_match.best_actions[0][index]]
        if not non_exploring:
            non_exploring.append(1)
        non_exploring_score = sum(non_exploring) / len(non_exploring)

        if correct.count() == len(correct):
            earliest_error = len(correct)
        else:
            #earliest_error = min(index for index, bit in enumerate(correct) if not bit) / len(correct)
            error_indices = [index for index in range(len(correct)) if not correct[index] and decoding_match.selected_action[index] == decoding_match.best_actions[0][index]]
            if error_indices:
                earliest_error = error_indices[0]
            else:
                earliest_error = len(correct)
        earliest_error /= len(correct)

        payoffs = []
        for index in range(self._encoder.action_size):
            #weights = self._weights[index]
            #payoff = sum(weight * bit for weight, bit in zip(weights, correct))

            #lower = index
            #upper = (index + self._ratio) % self._decoder.action_size
            #if lower < upper:
            #    payoff = correct[lower:upper].count()
            #else:
            #    payoff = correct[lower:].count() + correct[:upper].count()

            payoff = earliest_error**.5#max(non_exploring_score, earliest_error) ** .5#earliest_error * non_exploring_score#earliest_error#non_exploring_score#random.choice(non_exploring)

            payoffs.append(payoff)

        encoding_match.payoff = payoffs#score
        encoding_match.apply_payoff()

        decoding_match.payoff = tuple(correct)  #score
        decoding_match.apply_payoff()

        #return score

    def encode(self, bits):
        assert isinstance(bits, (bitstrings.BitString, bitstrings.BitCondition))
        assert len(bits) == self._decoder.action_size

        match = self._encoder.match(bits)
        return match.best_actions[0]

    def decode(self, bits):
        assert isinstance(bits, (bitstrings.BitString, bitstrings.BitCondition))
        assert len(bits) == self._encoder.action_size

        match = self._decoder.match(bits)
        return match.best_actions[0]

    def test(self, bits):
        assert isinstance(bits, (bitstrings.BitString, bitstrings.BitCondition))
        assert len(bits) == self._decoder.action_size

        reconstructed = self.decode(self.encode(bits))
        correct = bits ^ ~reconstructed
        return correct.count() / len(correct)


class ExplanatoryClassifierSetAutoEncoder:

    def __init__(self, encoder_algorithm, input_size):
        self._encoder = ClassifierSet(encoder_algorithm, [0, 1])
        self._encoder.


if __name__ == "__main__":
    from xcs import XCSAlgorithm
    #from ics import ICSAlgorithm

    input_size = 10#20
    encoded_size = 50#10
    #max_encoded_size = 50

    # False, False, True: 10000 0.7735099999999999 0.9111648946711803
    # False, False, False: 10000 0.7588499999999998 0.835536293872216
    # True, False, True: 10000 0.7570800000000026 0.904976281675563
    # True, True, False: 10000 0.7200399999999999 0.707286329391419
    # True, True, True: 10000 0.7166600000000032 0.7808882971658461
    # False, True, True: 10000 0.715649999999995 0.7477449199622611
    # True, False, False: 10000 0.7070999999999988 0.7361527224034019
    # False, True, False: 4700 0.6421489361702143 0.5987712765326559

    # After adding elif to if/elif/else at top of _update_fitness:
    # False, False, True: 10000 0.7639300000000004 0.8768575777793465
    # False, True, True: 8900 0.6295280898876382 0.5681276108508554
    # NOTE: I think that before this block was added, the rank-based
    # error was effectively ignored, so the scores in the first block
    # should probably be ignored.

    e_algorithm = XCSAlgorithm()
    e_algorithm.averaged_error = False#True
    e_algorithm.relative_error = False#False
    e_algorithm.rank_based_accuracy = True#False
    e_algorithm.learning_rate = .1
    e_algorithm.wildcard_probability = 1 - 1 / input_size
    e_algorithm.exploration_probability = 1 / encoded_size * .05#.001#0#.001#.01#0#.1 / encoded_size#.5 / 20
    #e_algorithm.initial_error = -1

    d_algorithm = XCSAlgorithm()
    d_algorithm.averaged_error = False#True
    d_algorithm.relative_error = False#False
    d_algorithm.rank_based_accuracy = True#False
    e_algorithm.learning_rate = .1#.1
    e_algorithm.wildcard_probability = 1 - 1 / encoded_size
    d_algorithm.exploration_probability = 1 / input_size * .5#.01#0#.01#.1 / input_size

    autoencoder = ClassifierSetAutoEncoder(e_algorithm, input_size, d_algorithm, encoded_size)#1)
    average = 0
    recent = 0
    for cycle in range(10000):
        bits = bitstrings.BitString.random(input_size // 2)
        bits += bitstrings.BitString(reversed(bits), input_size // 2)
        score = autoencoder.test(bits)
        autoencoder.train(bits)
        average += (score - average) / (cycle + 1)
        recent += (score - recent) / min(cycle + 1, 1000)
        if cycle % 100 == 99:
            print(cycle + 1, average, recent)
            encoded = autoencoder.encode(bits)
            decoded = autoencoder.decode(encoded)
            wrong = decoded ^ bits
            print(bits, '=>', encoded, '=>', decoded, '(' + str(wrong) + ',', str(wrong.count()) + ')')
            print()
            #if encoded_size < max_encoded_size:# and cycle % 1000 == 999:
            #    autoencoder.extend()
