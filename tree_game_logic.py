from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Set, Tuple, Any
from project_backend import QuantumEngine
Position = Tuple[int, int]


@dataclass
class PlayerState:
    #Stores the state of a single player.
    player_id: int
    row: int
    col: int
    alive: bool = True
    has_won: bool = False
    last_measurement: Optional[str] = None
    last_direction: Optional[str] = None
    last_weight: Optional[int] = None


class TreeBoard:
    """
    Represents the board layout for the tree game.

    The tree narrows as the player moves upward:
        row 6 -> cols -6..6
        row 5 -> cols -5..5
        ...
        row 0 -> col 0 only
    """

    def __init__(
            # Initializes the board with optional walls and goal nodes.
        self,
        height: int = 7,
        walls: Optional[Set[Position]] = None,
        goal_nodes: Optional[Set[Position]] = None,
    ):
        self.height = height
        self.start_row = height - 1
        self.walls: Set[Position] = walls if walls is not None else set()
        self.goal_nodes: Set[Position] = goal_nodes if goal_nodes is not None else {(0, 0)}

    def is_inside_tree(self, row: int, col: int) -> bool:
        #Returns True if a position is inside the valid tree shape.
        if row < 0 or row >= self.height:
            return False

        allowed = row
        return -allowed <= col <= allowed
        # For example, at row 3, allowed columns are -3, -2, -1, 0, 1, 2, 3.

    def is_wall(self, row: int, col: int) -> bool:
        #Returns True if a position is a wall.
        return (row, col) in self.walls

    def is_goal(self, row: int, col: int) -> bool:
        #Returns True if a position is a goal node.

        return (row, col) in self.goal_nodes

    def classify_position(self, row: int, col: int) -> str:
        """
        Returns one of:
        - 'outside_tree'
        - 'wall'
        - 'goal'
        - 'open'
        """
        if not self.is_inside_tree(row, col):
            return "outside_tree"
        if self.is_wall(row, col):
            return "wall"
        if self.is_goal(row, col):
            return "goal"
        return "open"

    def all_valid_nodes(self) -> List[Position]:
        #Returns every valid board position in the tree.
        nodes: List[Position] = []
        for row in range(self.height):
            for col in range(-row, row + 1):
                nodes.append((row, col))
        return nodes


class TreeGameLogic:
    """
    Main rules for the game.

    Responsibilities:
    - manage players
    - manage the board
    - call the quantum backend
    - apply weighted movement
    - determine win/loss/game-over state

    This class is meant to be called by a controller or GUI.
    """

    def __init__(
            # Initializes the game state, including players, board, and quantum engine.
        self,
        num_players: int = 1,
        board_height: int = 7,
        walls: Optional[Set[Position]] = None,
        goal_nodes: Optional[Set[Position]] = None,
        start_positions: Optional[List[Position]] = None,
    ):  # Validates num_players and initializes the game state.
        if num_players not in (1):
            raise ValueError("num_players must be 1")
        
        self.num_players = num_players
        self.board = TreeBoard(height=board_height, walls=walls, goal_nodes=goal_nodes)
        self.engine = QuantumEngine()

        self.turn_number = 0
        self.game_over = False
        self.winner_ids: List[int] = []

        default_starts = [(self.board.start_row, 0), (self.board.start_row, 1)]
        starts = start_positions if start_positions is not None else default_starts[:num_players]

        if len(starts) != num_players:
            raise ValueError("start_positions must contain one position per player")

        self.players: Dict[int, PlayerState] = {}
        for i in range(num_players):
            row, col = starts[i]
            self.players[i + 1] = PlayerState(player_id=i + 1, row=row, col=col)

        # Tracks the gate history used by the backend.
        self.history: List[tuple] = []

    # ---------------------------------------------------------
    # Public state helpers
    # ---------------------------------------------------------

    def get_game_state(self) -> Dict[str, Any]:
        #Returns the full game state in a GUI friendly format.

        return {
            "turn_number": self.turn_number,
            "game_over": self.game_over,
            "winner_ids": list(self.winner_ids),
            "players": {pid: asdict(player) for pid, player in self.players.items()},
            "walls": list(self.board.walls),
            "goal_nodes": list(self.board.goal_nodes),
            "height": self.board.height,
            "num_players": self.num_players,
        }

    def get_board_snapshot(self) -> List[Dict[str, Any]]:
        #Returns every valid board node with information a GUI can draw.

        snapshot: List[Dict[str, Any]] = []
        player_positions = {
            (p.row, p.col): p.player_id
            for p in self.players.values()
            if p.alive or p.has_won
        }

        for row, col in self.board.all_valid_nodes():
            cell_type = "open"
            if (row, col) in self.board.walls:
                cell_type = "wall"
            elif (row, col) in self.board.goal_nodes:
                cell_type = "goal"

            snapshot.append({
                "row": row,
                "col": col,
                "cell_type": cell_type,
                "player_id": player_positions.get((row, col)),
            })

        return snapshot

    # ---------------------------------------------------------
    # Move preview helpers
    # ---------------------------------------------------------

    # A single move simulation for the GUI (for reference)

    def preview_single_move(self, player_id: int, weight: int) -> Dict[str, Any]:
        self._validate_weight(weight)
        player = self._get_valid_player(player_id)

        left_pos = (player.row - 1, player.col - weight)
        right_pos = (player.row - 1, player.col + weight)

        return {
            #Returns the preview of a single move for one player, including the potential new positions and their classifications.
            "player_id": player_id,
            "weight": weight,
            "current_position": (player.row, player.col),
            "left_preview": {
                "position": left_pos,
                "classification": self.board.classify_position(*left_pos),
            },
            "right_preview": {
                "position": right_pos,
                "classification": self.board.classify_position(*right_pos),
            },
        }

    # ---------------------------------------------------------
    # Validation helpers (Checks logic cases for the weights)
    # ---------------------------------------------------------

    def _validate_weight(self, weight: int) -> None:
        if not isinstance(weight, int):
            raise TypeError("weight must be an integer")
        if weight < 1:
            raise ValueError("weight must be at least 1")
    def _get_valid_player(self, player_id: int) -> PlayerState:
        if player_id not in self.players:
            raise ValueError(f"Invalid player_id: {player_id}")

        player = self.players[player_id]
        if not player.alive:
            raise ValueError(f"Player {player_id} is no longer alive")
        if player.has_won:
            raise ValueError(f"Player {player_id} has already won")

        return player

    # ---------------------------------------------------------
    # Movement and rule helpers
    # ---------------------------------------------------------

    def _apply_measurement_to_position(
            # Determines the new position and direction based on the measurement result and weight.
        self,
        row: int,
        col: int,
        measured_bit: str,
        weight: int,
    ) -> Tuple[Position, str]:
        
        #Moves up one row and drifts left or right by the chosen weight.
        new_row = row - 1

        if measured_bit == "0":
            new_col = col - weight
            direction = f"Up-Left by {weight}"
        elif measured_bit == "1":
            new_col = col + weight
            direction = f"Up-Right by {weight}"
        else:
            raise ValueError(f"Unexpected measured_bit: {measured_bit}")

        return (new_row, new_col), direction

    def _resolve_new_position(
            # Applies the new position to the player state and determines if they hit a wall, fell outside the tree, reached a goal, or are still alive.
        self,
        player: PlayerState,
        new_pos: Position,
        measured_bit: str,
        direction: str,
        weight: int,
    ) -> Dict[str, Any]:
        
        row, col = new_pos
        status = self.board.classify_position(row, col)

        player.last_measurement = measured_bit
        player.last_direction = direction
        player.last_weight = weight

        if status == "outside_tree":
            player.alive = False
            return {
                "result": "fell_outside_tree",
                "position": new_pos,
                "player_alive": False,
                "player_won": False,
            }

        if status == "wall":
            player.alive = False
            player.row, player.col = row, col
            return {
                "result": "hit_wall",
                "position": new_pos,
                "player_alive": False,
                "player_won": False,
            }

        if status == "goal":
            player.row, player.col = row, col
            player.has_won = True
            return {
                "result": "win",
                "position": new_pos,
                "player_alive": True,
                "player_won": True,
            }

        player.row, player.col = row, col
        return {
            "result": "ok",
            "position": new_pos,
            "player_alive": True,
            "player_won": False,
        }

    def _update_game_over(self) -> None:
        # Checks if the game is over by looking for any winners or if all players are dead.
        alive_players = [p for p in self.players.values() if p.alive]
        winners = [p.player_id for p in self.players.values() if p.has_won]

        self.winner_ids = winners

        if winners:
            self.game_over = True
            return

        if not alive_players:
            self.game_over = True

    # ---------------------------------------------------------
    # Solo turn logic
    # ---------------------------------------------------------

    def take_single_player_turn(
        self,
        player_id: int,
        token_type: str,
        weight: int,
    ) -> Dict[str, Any]:
        """
        Runs one turn for one player.

        token_type examples:
        - 'Superposition'
        - 'Entanglement'
        - 'Right'
        - 'Left' (or any default value meaning remain in |0>)
        """
        if self.game_over:
            return {"error": "Game is already over."}
        # Validate inputs and get player state.
        self._validate_weight(weight)
        player = self._get_valid_player(player_id)

        # Prepare the quantum operation history for the backend.
        current_q = self.turn_number

        # Map token types to quantum gates and build the history.
        if token_type == "Superposition":
            self.history.append(("H", current_q))
        elif token_type == "Entanglement":
            if current_q == 0:
                self.history.append(("H", current_q))
            else:
                self.history.append(("CX", current_q - 1, current_q))
        elif token_type == "Right":
            self.history.append(("X", current_q))
        else:
            # "Left" / default leaves the state as |0>, so no gate is added.
            pass

                # The backend will treat the latest qubit (current_q) as the one to measure.
        measured_state, circuit = self.engine.build_and_measure(self.history)
        # Apply the measurement result to determine the new position and direction.
        new_pos, direction = self._apply_measurement_to_position(
            player.row,
            player.col,
            measured_state,
            weight,
        )
        # Resolve the new position, update player state, and determine if the game is over.
        resolution = self._resolve_new_position(
            player,
            new_pos,
            measured_state,
            direction,
            weight,
        )
        # Increment turn number and check for game over.
        self.turn_number += 1
        self._update_game_over()

        # Return a summary of the turn for the GUI/controller.
        return {
            "mode": "single_player_turn",
            "player_id": player_id,
            "turn_number": self.turn_number,
            "token_type": token_type,
            "weight": weight,
            "measurement": measured_state,
            "direction": direction,
            "resolution": resolution,
            "game_over": self.game_over,
            "winner_ids": list(self.winner_ids),
            "circuit": circuit,
            "players": {pid: asdict(p) for pid, p in self.players.items()},
        }

    # ---------------------------------------------------------
    # Debug/testing helper
    # ---------------------------------------------------------

    def render_ascii_board(self) -> str:
        """
        Renders the tree in plain text for quick testing.

        Symbols:
        . = open node
        X = wall
        G = goal
        1 = player 1
        2 = player 2
        """
        lines: List[str] = []
        player_pos_map = {
            (p.row, p.col): str(p.player_id)
            for p in self.players.values()
            if p.alive or p.has_won
        }

        max_width = self.board.height * 2 + 1

        for row in range(self.board.height):
            symbols: List[str] = []
            for col in range(-row, row + 1):
                pos = (row, col)
                if pos in player_pos_map:
                    symbol = player_pos_map[pos]
                elif pos in self.board.walls:
                    symbol = "X"
                elif pos in self.board.goal_nodes:
                    symbol = "G"
                else:
                    symbol = "."
                symbols.append(symbol)

            row_text = " ".join(symbols)
            lines.append(row_text.center(max_width * 2))

        return "\n".join(lines)
