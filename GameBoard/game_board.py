# MODULES
import pygame, sys
import os 

# initializes pygame

# ---------
# CONSTANTS
# ---------

# rgb: red green blue
RED = (255, 0, 0)
BG_COLOR = (231, 225, 232)
LINE_COLOR = (0, 0, 0)
CIRCLE_COLOR = (239, 231, 200)
CROSS_COLOR = (66, 66, 66)
    
class Screen():
    def __init__(self, env):
        if env.show_screen:
            pygame.init()
            self.env = env
            self.WIDTH = 800
            self.HEIGHT = 800
            self.LINE_WIDTH = 1
            self.SQUARE_SIZE = int(self.HEIGHT / 20)
            self.color_A = (255, 172,  88)
            self.color_B = (129, 188, 255)
            self.dir_path = os.path.dirname(os.path.realpath(__file__))
            if env.show_screen:
                self.load_image()
                pygame.display.set_caption( 'ProCon-2020' ) 

    def render(self):
        pygame.display.update()

    def load_image(self):
        self.agent_A_img = pygame.transform.scale(
            pygame.image.load(self.dir_path + '/images/X1.png'), (self.SQUARE_SIZE, self.SQUARE_SIZE))
        self.agent_B_img = pygame.transform.scale(
            pygame.image.load(self.dir_path + '/images/O1.png'), (self.SQUARE_SIZE, self.SQUARE_SIZE))
        self.background_img = pygame.transform.scale(
            pygame.image.load(self.dir_path + '/images/background.jpg'), (966, 966))
        self.table_img =  pygame.transform.scale(
            pygame.image.load(self.dir_path + '/images/board.png'), (400, 350))
        self.win_img =  pygame.transform.scale(
            pygame.image.load(self.dir_path + '/images/win.jpg'), (300, 350))
        
    def coord(self, x, y):
        return x * self.SQUARE_SIZE, y * self.SQUARE_SIZE
    
    def setup(self, env): 
        self.h = env.height
        self.w = env.width
        self.screen = pygame.display.set_mode(self.coord(self.h + 8, self.w))  
        self.screen.fill( BG_COLOR )
        self.draw_lines()
        self.screen.blit(self.background_img, self.coord(self.h, 0))
        self.show_infor_winner()
        pygame.display.update()

    def show_infor_winner(self):
        self.screen.blit(self.table_img, self.coord(self.h - 1, -2))
        
        myFont = pygame.font.SysFont("Times New Roman", 30)
        
        color = (255, 178, 21)
        
        SA = myFont.render("    : " + str(self.env.players[0].n_wins), 0, color)
        SB = myFont.render("    : " + str(self.env.players[1].n_wins), 0, color)
        
    
        self.screen.blit(SA, self.coord(self.h + 1, 1))
        self.screen.blit(SB, self.coord(self.h + 1, 2))
        self.screen.blit(self.agent_A_img, (self.h * self.SQUARE_SIZE + 30, -5 + 1 * self.SQUARE_SIZE))
        self.screen.blit(self.agent_B_img, (self.h  * self.SQUARE_SIZE+ 30, -5 + 2 * self.SQUARE_SIZE))
    
    def start(self):
        game_over = False
        # -------
        player = 0
        while not game_over:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    sys.exit()
                
                if event.type == pygame.MOUSEBUTTONDOWN and not game_over:
                    mouseX = event.pos[0] # x
                    mouseY = event.pos[1] # y
                    
                    clicked_row = int(mouseY // self.SQUARE_SIZE)
                    clicked_col = int(mouseX // self.SQUARE_SIZE)
                    x = clicked_col
                    y = clicked_row
                    if self.env.board[player][x][y] + self.env.board[1 - player][x][y] == 0:
                        self.draw(x, y, player)
                        self.env.board[player][x][y] = 1
                        self.render()
                        if self.env.check_game_ended(self.env.board, player, (x, y)):
                            self.env.players[player].n_wins += 1
                            self.reset_screen()
                        
                        player = 1 - player
                        
                        
            pygame.display.update()
            
    def draw(self, x, y, player_ID):
        player_img = self.agent_A_img if player_ID == 0 else self.agent_B_img
        self.screen.blit(player_img, self.coord(x, y))
        
    
    def draw_lines(self):
        for i in range(self.w):
            pygame.draw.line(self.screen, LINE_COLOR, (0, i * self.SQUARE_SIZE), 
                              (self.h * self.SQUARE_SIZE, i * self.SQUARE_SIZE), self.LINE_WIDTH )
        for i in range(self.h):
            pygame.draw.line(self.screen, LINE_COLOR, (i * self.SQUARE_SIZE, 0),
                             (i * self.SQUARE_SIZE, self.w * self.SQUARE_SIZE), self.LINE_WIDTH )
        
    def reset_screen(self):
        self.screen.fill( BG_COLOR )
        self.screen.blit(self.background_img, self.coord(self.h, 0))
        self.draw_lines()
        for i in range(self.h):
            for j in range(self.w):
                self.env.board[0][i][j] = 0
                self.env.board[1][i][j] = 0
                    
        self.show_infor_winner()
