%option noyywrap
%{
#include <stdio.h>
%}
%%
0[xX][0-9a-fA-F]+   { printf("HEX: %s\n", yytext); }
[0-9]+\.[0-9]+      { printf("FLOAT: %s\n", yytext); }
0[0-7]+             { printf("OCT: %s\n", yytext); }
0|[1-9][0-9]*       { printf("DEC: %s\n", yytext); }
[ \t\r\n]+          { /* skip whitespace */ }
.                   { printf("UNHANDLED: %s\n", yytext); }
%%
int main(void) { yylex(); return 0; }
