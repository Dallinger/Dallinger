# Copyright 2012, 2014, 2015 Dominik Heier
#
# This file is part of coffee-snake.
#
# coffee-snake is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

class Game extends atom.Game
  
  constructor: (h, w, ps)  ->
    super
    atom.input.bind atom.key.LEFT_ARROW, 'move_left'
    atom.input.bind atom.key.RIGHT_ARROW, 'move_right'
    atom.input.bind atom.key.UP_ARROW, 'move_up'
    atom.input.bind atom.key.DOWN_ARROW, 'move_down'
    atom.input.bind atom.key.SPACE, 'toggle_pause'

    @height = h
    @width = w
    @pixelsize = ps

    # Style the canvas
    window.onresize = (e) -> return
    canvas_container = document.getElementById('canvas_container')
    canvas_container.style.width = @width *  @pixelsize + "px"
    atom.canvas.style.border = "#fff 1px solid"
    atom.canvas.style.position = "relative"
    atom.canvas.height = @height * @pixelsize 
    atom.canvas.width = @width * @pixelsize

    #Start the game
    @startGame()
  
  startGame: ->
    # Initialize 
    _x = Math.floor(@width / 2)
    _y = Math.floor(@height / 2)
    @snake = [ [ _x, _y ], [ --_x, _y ], [ --_x, _y ], [ --_x, _y ] ]
    @dir = ""
    @newdir = "right"
    @score = 0
    @gstarted = true
    @gpaused = false
    @food = []
    @last_dt = 0.00
    @delay = 0.08
    @noshow = true
    @gpaused = true
    [@tx , @ty] = [@width * @pixelsize, @height * @pixelsize]

    @genFood() # generate food pixel
    @showIntro() # show intro screen

  genFood: ->
    x = undefined
    y = undefined
    loop
      x = Math.floor(Math.random() * (@width - 1))
      y = Math.floor(Math.random() * (@height - 1))
      break unless @testCollision(x, y)
    @food = [ x, y ]

  drawFood: ->
    atom.context.beginPath()
    atom.context.arc (@food[0] * @pixelsize) + @pixelsize / 2, (@food[1] * @pixelsize) + @pixelsize / 2, @pixelsize / 2, 0, Math.PI * 2, false
    atom.context.fill()

  drawSnake: ->
    i = 0
    l = @snake.length
    while i < l
      x = @snake[i][0]
      y = @snake[i][1]
      atom.context.fillRect x * @pixelsize, y * @pixelsize, @pixelsize, @pixelsize
      i++

  testCollision: (x, y) ->
    return true  if x < 0 or x > @width - 1
    return true  if y < 0 or y > @height - 1
    i = 0
    l = @snake.length

    while i < l
      return true  if x is @snake[i][0] and y is @snake[i][1]
      i++
    false
  
  endGame: ->
    @gstarted = false
    @noshow = true
    atom.context.fillStyle = "#fff"
    atom.context.strokeStyle = '#000'

    # Game over
    [mess, x , y] = ["Game Over", @tx / 2 , @ty / 2.4]
    atom.context.font = "bold 30px monospace"
    atom.context.textAlign = "center"
    atom.context.fillText mess, x, y
    atom.context.strokeText mess, x, y

    # score
    atom.context.font = "bold 25px monospace"
    [mess, x , y] = ["Score: " + @score, @tx / 2 , @ty / 1.7]
    atom.context.fillText mess, x, y
    atom.context.strokeText mess, x, y

  togglePause: ->
    unless @gpaused
      @noshow = true
      @gpaused = true
      [mess, x , y] = ["Paused", @tx / 2, @ty / 2]
      atom.context.fillStyle = "#fff"
      atom.context.font = "bold 30px monospace"
      atom.context.textAlign = "center"
      atom.context.fillText mess, x, y
      atom.context.strokeText mess, x, y
    else
      @gpaused = false
      @noshow = false 

  showIntro: ->
    atom.context.fillStyle = "#fff"
    atom.context.font = "30px sans-serif"
    atom.context.textAlign = "center"
    atom.context.textAlign = "left"
    atom.context.font = "30px monospace"
    atom.context.fillText "Instructions:", 2 * @pixelsize, @ty / 3
    atom.context.font = "18px monospace"
    atom.context.fillText "Use arrow keys to change direction.", 2 * @pixelsize, @ty / 2.3
    atom.context.fillText "Press space to start/pause.", 2 * @pixelsize, @ty / 2.1 
    atom.context.fillText "Pro-tip: Press space now!", 2 * @pixelsize, @ty / 1.7 

  update: (dt) ->
    # Check keyboard input
    if atom.input.pressed 'move_left'
      @newdir = "left"  unless @dir is "right"
      console.log "left"
    else if atom.input.pressed 'move_up'
      @newdir = "up"  unless @dir is "down"
    else if atom.input.pressed  'move_right'
      @newdir = "right" unless @dir is "left"
    else if atom.input.pressed  'move_down'
      @newdir = "down"  unless @dir is "up"
    else if atom.input.pressed  'toggle_pause'
      unless @gstarted
        @eraseCanvas()
        @startGame()
      else
        @togglePause()

    # Slow down the game
    if @last_dt < @delay
      @last_dt += dt
      return
    else 
      @last_dt = 0.00
    
    # Don't do anything if game is paused or stopped
    return if not @gstarted or @gpaused

    # Update snake
    x = @snake[0][0]
    y = @snake[0][1]
    switch @newdir
      when "up"
        y--
      when "right"
        x++
      when "down"
        y++
      when "left"
        x--
    
    # Check for collision with self or wall
    if @testCollision(x, y)
      @endGame()
      return

    # Move the snake
    @snake.unshift [ x, y ]
    if x is @food[0] and y is @food[1]
      @score++
      @genFood()
    else
      @snake.pop()
    @dir = @newdir

  eraseCanvas: ->
    atom.context.fillStyle = "#000"
    atom.context.fillRect 0, 0, @width * @pixelsize, @height * @pixelsize
    atom.context.fillStyle = "#fff" 

  draw: ->
    unless @noshow
      @eraseCanvas()
      @drawFood()
      @drawSnake()

game = new Game(15, 20, 30)
game.run()
