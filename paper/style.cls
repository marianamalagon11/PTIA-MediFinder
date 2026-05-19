%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%                     CLASE PARA INFORMES                     %
%          Plantilla ECI basada en U Pontificia Chile         %
%               Creditos Github: @diegocostares               %
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{style}[2024/01/01 Plantilla ECI]

%----------------------------- CLASE BASE ----------------------------
\LoadClass[letterpaper,12pt]{article}

%----------------------------- CODIFICACIÓN Y FUENTES ----------------------------
\RequirePackage{fontspec}
\setmainfont{Times New Roman}

%----------------------------- PAQUETES ESENCIALES ----------------------------
\RequirePackage[spanish,es-tabla]{babel}
\RequirePackage[letterpaper,top=3cm,bottom=3cm,left=3cm,right=3cm]{geometry}
\RequirePackage{graphicx}
\RequirePackage{float}
\RequirePackage{setspace}
\RequirePackage{parskip}
\RequirePackage{fancyhdr}
\RequirePackage{titlesec}
\RequirePackage{caption}
\RequirePackage{subcaption}
\RequirePackage{amsmath}
\RequirePackage{amssymb}
\RequirePackage{listings}
\RequirePackage{xcolor}
\RequirePackage{tocloft}
\RequirePackage{enumitem}
\RequirePackage{pdfpages}
\RequirePackage{url}

%----------------------------- COLORES ----------------------------
\definecolor{rojoclaro}{RGB}{211, 47, 47}
\definecolor{grey}{RGB}{128,128,128}
\definecolor{silver}{RGB}{169,169,169}

%----------------------------- FORMATO DE SECCIONES ----------------------------
\titleformat{\section}[hang]
    {}
    {\color{rojoclaro}\LARGE\bfseries \thesection . \ }{0pt}
    {\color{rojoclaro}\LARGE\bfseries}
    []
    
\titleformat{\subsection}[hang]
    {}
    {\color{grey}\Large\bfseries \thesubsection. \ }{0pt}
    {\color{grey}\Large\bfseries}
    []
    
\titleformat{\subsubsection}[hang]
    {}
    {\color{silver}\large\bfseries \thesubsubsection. \ }{0pt}
    {\color{silver}\large\bfseries}
    []

%----------------------------- ENCABEZADOS Y PIES DE PÁGINA ----------------------------
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
\fancyfoot[C]{\thepage}

%----------------------------- FORMATO DE CÓDIGO ----------------------------
\lstset{
    basicstyle=\ttfamily\small,
    breaklines=true,
    frame=single,
    numbers=left,
    numberstyle=\tiny\color{grey},
    keywordstyle=\color{rojoclaro}\bfseries,
    commentstyle=\color{grey}\itshape,
    stringstyle=\color{grey},
    showstringspaces=false,
    tabsize=4,
    captionpos=b
}

%----------------------------- FORMATO DE TABLAS Y FIGURAS ----------------------------
\captionsetup[figure]{
    labelfont={color=rojoclaro,bf},
    textfont=it,
    labelsep=period
}

\captionsetup[table]{
    labelfont={color=rojoclaro,bf},
    textfont=it,
    labelsep=period
}

%----------------------------- ÍNDICES ----------------------------
\renewcommand{\cftsecleader}{\cftdotfill{\cftdotsep}}
\renewcommand{\cftsubsecleader}{\cftdotfill{\cftdotsep}}

%----------------------------- ESPACIADO ----------------------------
\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}

%----------------------------- LISTAS ----------------------------
\setlist[itemize]{leftmargin=*}
\setlist[enumerate]{leftmargin=*}

%----------------------------- BIBLIOGRAFÍA ----------------------------
\RequirePackage[backend=biber,style=apa,sorting=nyt,maxbibnames=99,giveninits=false]{biblatex}

% Espaciado mejorado para referencias
\setlength\bibitemsep{1.0\baselineskip}
\setlength\bibhang{1.5em}

% Formato de URLs - Permitir partir en cualquier lugar para que no se salgan
\setcounter{biburlnumpenalty}{0}
\setcounter{biburlucpenalty}{0}
\setcounter{biburllcpenalty}{0}

% Permitir partir URLs en cualquier carácter
\appto\UrlBreaks{\do\a\do\b\do\c\do\d\do\e\do\f\do\g\do\h\do\i\do\j\do\k\do\l\do\m\do\n\do\o\do\p\do\q\do\r\do\s\do\t\do\u\do\v\do\w\do\x\do\y\do\z}
\appto\UrlBreaks{\do\A\do\B\do\C\do\D\do\E\do\F\do\G\do\H\do\I\do\J\do\K\do\L\do\M\do\N\do\O\do\P\do\Q\do\R\do\S\do\T\do\U\do\V\do\W\do\X\do\Y\do\Z}
\appto\UrlBreaks{\do\1\do\2\do\3\do\4\do\5\do\6\do\7\do\8\do\9\do\0}
\appto\UrlBreaks{\do\-}

% Evitar que el texto siguiente se pegue a la URL
\renewbibmacro*{url+urldate}{%
  \printfield{url}%
  \iffieldundef{urlyear}
    {}
    {\setunit*{\addspace}%
     \printtext[parens]{\printurldate}}%
  \newunit\newblock}

% Sangría francesa para referencias
\defbibenvironment{bibliography}
  {\list{}
     {\setlength{\leftmargin}{\bibhang}%
      \setlength{\itemindent}{-\leftmargin}%
      \setlength{\itemsep}{\bibitemsep}%
      \setlength{\parsep}{\bibparsep}}}
  {\endlist}
  {\item}

%----------------------------- OTROS ----------------------------
\RequirePackage[colorlinks=true, linkcolor=black, urlcolor=blue, citecolor=black]{hyperref}

\hfuzz=\maxdimen
\hbadness=10000

\providecommand{\tightlist}{%
  \setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}

\endinput