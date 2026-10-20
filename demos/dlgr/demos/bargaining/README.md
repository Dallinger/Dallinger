# Bargaining

Pairs of participants bargain over the price of one item, in a real-time game.
One player is the seller, with a private cost, and the other is the buyer, with
a private value. Either can make or change an offer at any time, or accept the
other's, until the clock runs out. A deal pays the seller the price minus their
cost and the buyer their value minus the price, and each player's bonus is paid
from the saved outcome.

Each player's view holds only their own value, so the other player's stays
hidden until the game is over. The game is played by Dallinger's real-time
engine, as described in [Real-Time Games](../../realtime_games.html).
